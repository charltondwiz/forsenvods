import Foundation
import AVFoundation
import Vision
import CoreImage
import AppKit
import OpenAI // Using Swift OpenAI package

// ---------------------------------------------------------------------------
// Environment Variables Helper
// ---------------------------------------------------------------------------
func loadEnvFile() -> [String: String] {
    var env: [String: String] = [:]
    
    // Try to load from .env file
    let fileURL = URL(fileURLWithPath: ".env")
    guard let envData = try? Data(contentsOf: fileURL),
          let envString = String(data: envData, encoding: .utf8) else {
        return env
    }
    
    // Parse .env file (simple implementation)
    let lines = envString.components(separatedBy: .newlines)
    for line in lines {
        let trimmedLine = line.trimmingCharacters(in: .whitespacesAndNewlines)
        // Skip comments and empty lines
        if trimmedLine.isEmpty || trimmedLine.hasPrefix("#") {
            continue
        }
        
        // Parse KEY=VALUE format
        let components = trimmedLine.components(separatedBy: "=")
        if components.count >= 2 {
            let key = components[0].trimmingCharacters(in: .whitespacesAndNewlines)
            // Join the rest with = in case the value contains = characters
            let value = components[1...].joined(separator: "=").trimmingCharacters(in: .whitespacesAndNewlines)
            
            // Remove quotes if present
            var processedValue = value
            if (value.hasPrefix("\"") && value.hasSuffix("\"")) || (value.hasPrefix("'") && value.hasSuffix("'")) {
                let startIndex = value.index(after: value.startIndex)
                let endIndex = value.index(before: value.endIndex)
                processedValue = String(value[startIndex..<endIndex])
            }
            
            env[key] = processedValue
        }
    }
    
    return env
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
let VIDEO_FILE = "chat_with_video.mp4"
let FRAME_DIR = "frames"
let TITLE_DIR = "titles"
let SEGMENT_DIR = "segments"
let INTERVAL_SECONDS = 3    // seconds between sampled frames
let FRAME_JUMP = 3          // stride for coarse end detection
let MAX_GAP_SECONDS = 60
let MIN_SEGMENT_DURATION = 5
let SIMILARITY_THRESHOLD = 0.35
let DEBUG_MODE = true

// Load environment variables from .env file first
let envVariables = loadEnvFile()

// Setup OpenAI client - check .env file first, then system environment variables
let openAIAPIKey = envVariables["OPENAI_API_KEY"] ?? ProcessInfo.processInfo.environment["OPENAI_API_KEY"] ?? ""
if openAIAPIKey.isEmpty {
    print("OPEN AI API KEY NOT FOUND! Please set it in .env file or as environment variable.")
    exit(1)
}

let openAI = OpenAI(apiToken: openAIAPIKey)
let MODEL = "gpt-4o-mini"  // adjust as needed

// Create folders if they don't exist
for dirPath in [FRAME_DIR, TITLE_DIR, SEGMENT_DIR] {
    try? FileManager.default.createDirectory(atPath: dirPath, withIntermediateDirectories: true, attributes: nil)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
func getFramePath(idx: Int) -> String {
    return "\(FRAME_DIR)/frame_\(String(format: "%04d", idx+1)).jpg"
}

func getTitlePath(idx: Int) -> String {
    return "\(TITLE_DIR)/frame_\(String(format: "%04d", idx+1)).jpg"
}

// Fuzzy-similarity utilities
func calculateSimilarity(a: String, b: String) -> Double {
    if a.isEmpty || b.isEmpty {
        return 0.0
    }
    
    // Using Levenshtein distance for string similarity
    let distance = a.levenshteinDistance(to: b)
    let maxLength = max(a.count, b.count)
    return 1.0 - Double(distance) / Double(maxLength)
}

func isSameYoutubeId(id1: String?, id2: String?) -> Bool {
    guard let id1 = id1, let id2 = id2, !id1.isEmpty, !id2.isEmpty else {
        return false
    }
    
    if id1.lowercased() == id2.lowercased() {
        return true
    }
    
    let score = calculateSimilarity(a: id1, b: id2) >= SIMILARITY_THRESHOLD
    print("\(id1) \(id2) SCORE: \(score)")
    return score
}

func isSimilarTitle(t1: String?, t2: String?) -> Bool {
    guard let t1 = t1, let t2 = t2, !t1.isEmpty, !t2.isEmpty else {
        return false
    }
    
    if t1.contains("No Title") || t2.contains("No Title") {
        return false
    }
    
    return calculateSimilarity(a: t1, b: t2) >= SIMILARITY_THRESHOLD
}

// ---------------------------------------------------------------------------
// Vision framework text recognition (OCR)
// ---------------------------------------------------------------------------
func extractTextFromImage(path: String, completion: @escaping (String?) -> Void) {
    guard let image = NSImage(contentsOfFile: path),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        completion(nil)
        return
    }
    
    let request = VNRecognizeTextRequest { (request, error) in
        guard error == nil,
              let observations = request.results as? [VNRecognizedTextObservation] else {
            completion(nil)
            return
        }
        
        let recognizedText = observations.compactMap { observation in
            observation.topCandidates(1).first?.string
        }.joined(separator: " ")
        
        completion(recognizedText.trimmingCharacters(in: .whitespacesAndNewlines))
    }
    
    // Configure for accurate OCR
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    
    do {
        try handler.perform([request])
    } catch {
        print("Error performing Vision request: \(error)")
        completion(nil)
    }
}

// ---------------------------------------------------------------------------
// YouTube ID extraction via regex
// ---------------------------------------------------------------------------
func extractYoutubeId(text: String?) -> String? {
    guard let text = text, !text.isEmpty else {
        return nil
    }
    
    let patterns = [
        "(?:youtu\\.be/|youtube\\.com/watch\\?v=)([\\w-]{11})",
        "youtube\\.com/embed/([\\w-]{11})",
        "([\\w-]{11})"
    ]
    
    for pattern in patterns {
        let regex = try? NSRegularExpression(pattern: pattern, options: [])
        if let match = regex?.firstMatch(in: text, options: [], range: NSRange(location: 0, length: text.utf16.count)) {
            if match.numberOfRanges > 1, let range = Range(match.range(at: 1), in: text) {
                return String(text[range])
            }
        }
    }
    
    return nil
}

// ---------------------------------------------------------------------------
// GPT-based title extraction (called once)
// ---------------------------------------------------------------------------
func getTitleWithGPT(framePath: String, completion: @escaping (String) -> Void) {
    guard let imageData = try? Data(contentsOf: URL(fileURLWithPath: framePath)) else {
        completion("")
        return
    }
    
    let base64Image = imageData.base64EncodedString()
    
    // Build the chat parameters using the multimodal schema
    let messages: [Chat.Message] = [
        .init(role: .system, content: "You are an assistant that extracts video titles from provided images. Respond strictly with JSON: {\"title\": \"…\"}."),
        .init(role: .user, content: [
            .init(
                type: .text,
                text: "Forsen is watching a YouTube video. What is the exact title? Respond ONLY with JSON in the form:\n{\"title\":\"<the video's title>\"}."
            ),
            .init(
                type: .imageUrl,
                imageUrl: .init(url: "data:image/jpeg;base64,\(base64Image)")
            )
        ])
    ]
    
    // Call the OpenAI API
    openAI.chats(
        query: .init(model: MODEL, messages: messages)
    ) { result in
        switch result {
        case .success(let response):
            if let content = response.choices.first?.message.content {
                do {
                    if let data = content.data(using: .utf8),
                       let json = try JSONSerialization.jsonObject(with: data) as? [String: String],
                       let title = json["title"] {
                        completion(title)
                    } else {
                        completion("")
                    }
                } catch {
                    print("JSON parsing error: \(error)")
                    completion("")
                }
            } else {
                completion("")
            }
        case .failure(let error):
            print("OpenAI API error: \(error)")
            completion("")
        }
    }
}

// ---------------------------------------------------------------------------
// Frame extraction
// ---------------------------------------------------------------------------
func extractFramesFromVideo(completion: @escaping () -> Void) {
    // Check if frames already exist
    let fileManager = FileManager.default
    if let files = try? fileManager.contentsOfDirectory(atPath: FRAME_DIR), !files.isEmpty {
        print("ℹ️ Using existing frames in \(FRAME_DIR)")
        completion()
        return
    }
    
    print("Extracting frames every \(INTERVAL_SECONDS)s…")
    
    // Use FFmpeg command through Process
    let titleTask = Process()
    titleTask.executableURL = URL(fileURLWithPath: "/usr/local/bin/ffmpeg")
    titleTask.arguments = [
        "-i", VIDEO_FILE,
        "-vf", "fps=1/\(INTERVAL_SECONDS),crop=in_w*0.4:in_h*0.0475:in_w*0.03:in_h*0.875",
        "\(TITLE_DIR)/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ]
    
    do {
        try titleTask.run()
        titleTask.waitUntilExit()
        
        let frameTask = Process()
        frameTask.executableURL = URL(fileURLWithPath: "/usr/local/bin/ffmpeg")
        frameTask.arguments = [
            "-i", VIDEO_FILE,
            "-vf", "fps=1/\(INTERVAL_SECONDS),crop=in_w*0.4:in_h*0.06:in_w*0.055:in_h*0.03",
            "\(FRAME_DIR)/frame_%04d.jpg",
            "-hide_banner", "-loglevel", "error"
        ]
        
        try frameTask.run()
        frameTask.waitUntilExit()
        
        print("✅ Frames & title crops extracted.")
        completion()
    } catch {
        print("Error extracting frames: \(error)")
    }
}

// ---------------------------------------------------------------------------
// Binary-search for exact segment start (uses OCR)
// ---------------------------------------------------------------------------
func findExactStart(idx: Int, ytId: String, total: Int, lastEnd: Int, completion: @escaping (Int) -> Void) {
    let lookback = Int(MAX_GAP_SECONDS / INTERVAL_SECONDS) + 1
    let start = max(lastEnd + 1, idx - lookback)
    let end = idx
    var res = idx
    
    // Get reference text at the detected frame
    extractTextFromImage(path: getFramePath(idx: idx)) { refText in
        let refText = refText ?? ""
        
        func binarySearch(from: Int, to: Int) {
            if from > to {
                completion(res)
                return
            }
            
            let mid = (from + to) / 2
            extractTextFromImage(path: getFramePath(idx: mid)) { text in
                let text = text ?? ""
                let cid = extractYoutubeId(text: text)
                
                // Check for match
                if (cid != nil && isSameYoutubeId(id1: cid, id2: ytId)) || 
                   calculateSimilarity(a: text, b: refText) >= SIMILARITY_THRESHOLD {
                    res = mid
                    binarySearch(from: from, to: mid - 1)
                } else {
                    binarySearch(from: mid + 1, to: to)
                }
            }
        }
        
        binarySearch(from: start, to: end)
    }
}

// ---------------------------------------------------------------------------
// Merge overlapping or similar segments
// ---------------------------------------------------------------------------
func mergeSimilarSegments(segments: [(String, Int, Int, String)]) -> [(String, Int, Int, String)] {
    if segments.isEmpty {
        return []
    }
    
    let sortedSegments = segments.sorted { $0.1 < $1.1 }
    var merged: [(String, Int, Int, String)] = []
    var i = 0
    
    while i < sortedSegments.count {
        var (cid, st, ed, title) = sortedSegments[i]
        var j = i + 1
        
        while j < sortedSegments.count {
            let (ncid, nst, ned, ntitle) = sortedSegments[j]
            let gap = nst - ed
            
            if gap <= MAX_GAP_SECONDS && (isSameYoutubeId(id1: cid, id2: ncid) || isSimilarTitle(t1: title, t2: ntitle)) {
                ed = max(ed, ned)
                cid = ncid.count > cid.count ? ncid : cid
                title = ntitle.count > title.count ? ntitle : title
                j += 1
            } else {
                break
            }
        }
        
        merged.append((cid, st, ed, title))
        i = j
    }
    
    return merged
}

// ---------------------------------------------------------------------------
// Segment detection using Vision OCR for IDs and a single GPT call for title
// ---------------------------------------------------------------------------
func findYoutubeSegments(completion: @escaping ([(String, Int, Int, String)]) -> Void) {
    extractFramesFromVideo {
        // Count frames
        let fileManager = FileManager.default
        guard let contents = try? fileManager.contentsOfDirectory(atPath: FRAME_DIR) else {
            completion([])
            return
        }
        
        let total = contents.filter { $0.hasSuffix(".jpg") }.count
        var titleMap: [String: String] = [:]   // yt_id → extracted title
        var raw: [(String, Int, Int, String)] = []
        var lastEnd = -1
        var idx = 0
        
        func processNextFrame() {
            if idx >= total {
                // We're done, merge segments and return
                let merged = mergeSimilarSegments(segments: raw)
                completion(merged)
                return
            }
            
            if idx % 50 == 0 {
                print("Progress: \(idx)/\(total)")
            }
            
            extractTextFromImage(path: getFramePath(idx: idx)) { text in
                guard let text = text else {
                    idx += FRAME_JUMP
                    processNextFrame()
                    return
                }
                
                let ytId = extractYoutubeId(text: text)
                
                if let ytId = ytId, idx > lastEnd {
                    // If we've never seen this video-id, extract its title
                    if titleMap[ytId] == nil {
                        let titleFrame = getTitlePath(idx: idx)
                        getTitleWithGPT(framePath: titleFrame) { title in
                            titleMap[ytId] = title
                            print("🎥 Extracted title for \(ytId): \(title)")
                            
                            // Find exact segment boundaries
                            findExactStart(idx: idx, ytId: ytId, total: total, lastEnd: lastEnd) { startF in
                                let startFrame = max(lastEnd + 1, startF - 1, 0)
                                
                                // Coarse jump to find next change (end of segment)
                                var nf = startFrame + 1
                                func findEndOfSegment() {
                                    if nf >= total {
                                        let endFrame = total - 1
                                        raw.append((
                                            ytId,
                                            startFrame * INTERVAL_SECONDS,
                                            endFrame * INTERVAL_SECONDS,
                                            titleMap[ytId] ?? ""
                                        ))
                                        lastEnd = endFrame
                                        idx = endFrame + 1
                                        processNextFrame()
                                        return
                                    }
                                    
                                    extractTextFromImage(path: getFramePath(idx: nf)) { frameText in
                                        let nextId = extractYoutubeId(text: frameText)
                                        if nextId == nil {
                                            nf += FRAME_JUMP
                                            findEndOfSegment()
                                        } else {
                                            let endFrame = nf - 1
                                            raw.append((
                                                ytId,
                                                startFrame * INTERVAL_SECONDS,
                                                endFrame * INTERVAL_SECONDS,
                                                titleMap[ytId] ?? ""
                                            ))
                                            lastEnd = endFrame
                                            idx = endFrame + 1
                                            processNextFrame()
                                        }
                                    }
                                }
                                findEndOfSegment()
                            }
                        }
                    } else {
                        // We already have the title, just find segment boundaries
                        findExactStart(idx: idx, ytId: ytId, total: total, lastEnd: lastEnd) { startF in
                            let startFrame = max(lastEnd + 1, startF - 1, 0)
                            
                            // Coarse jump to find next change
                            var nf = startFrame + 1
                            func findEndOfSegment() {
                                if nf >= total {
                                    let endFrame = total - 1
                                    raw.append((
                                        ytId,
                                        startFrame * INTERVAL_SECONDS,
                                        endFrame * INTERVAL_SECONDS,
                                        titleMap[ytId] ?? ""
                                    ))
                                    lastEnd = endFrame
                                    idx = endFrame + 1
                                    processNextFrame()
                                    return
                                }
                                
                                extractTextFromImage(path: getFramePath(idx: nf)) { frameText in
                                    let nextId = extractYoutubeId(text: frameText)
                                    if nextId == nil {
                                        nf += FRAME_JUMP
                                        findEndOfSegment()
                                    } else {
                                        let endFrame = nf - 1
                                        raw.append((
                                            ytId,
                                            startFrame * INTERVAL_SECONDS,
                                            endFrame * INTERVAL_SECONDS,
                                            titleMap[ytId] ?? ""
                                        ))
                                        lastEnd = endFrame
                                        idx = endFrame + 1
                                        processNextFrame()
                                    }
                                }
                            }
                            findEndOfSegment()
                        }
                    }
                } else {
                    idx += FRAME_JUMP
                    processNextFrame()
                }
            }
        }
        
        // Start processing frames
        processNextFrame()
    }
}

// ---------------------------------------------------------------------------
// Clip extraction
// ---------------------------------------------------------------------------
func extractSegmentClips(segments: [(String, Int, Int, String)]) {
    do {
        try FileManager.default.createDirectory(atPath: SEGMENT_DIR, withIntermediateDirectories: true, attributes: nil)
        
        for (i, (ytId, st, ed, title)) in segments.enumerated() {
            // Create safe filename
            let safeTitleRegex = try NSRegularExpression(pattern: "[\\\\/*?:\"<>|]", options: [])
            let safeTitle = safeTitleRegex.stringByReplacingMatches(
                in: title,
                options: [],
                range: NSRange(location: 0, length: title.utf16.count),
                withTemplate: ""
            )
            
            let truncatedTitle = "Forsen Reacts to \(safeTitle.prefix(78)).mp4"
            
            // Get unique filename
            func getUniqueFilename(baseName: String) -> String {
                let fileURL = URL(fileURLWithPath: baseName)
                let name = fileURL.deletingPathExtension().lastPathComponent
                let ext = fileURL.pathExtension
                
                var candidate = "\(SEGMENT_DIR)/\(baseName)"
                var part = 2
                
                while FileManager.default.fileExists(atPath: candidate) {
                    candidate = "\(SEGMENT_DIR)/\(name) Part \(part).\(ext)"
                    part += 1
                }
                
                return candidate
            }
            
            let output = getUniqueFilename(baseName: String(truncatedTitle.prefix(100)))
            let duration = ed - st
            
            print("Extracting \(i+1)/\(segments.count): \(ytId) (\(duration)s) → \(output)")
            
            // Use FFmpeg for extraction
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/local/bin/ffmpeg")
            task.arguments = [
                "-ss", String(st), "-i", VIDEO_FILE,
                "-t", String(duration), "-c:v", "copy", "-c:a", "copy", output
            ]
            
            do {
                try task.run()
                task.waitUntilExit()
                
                if task.terminationStatus != 0 {
                    throw NSError(domain: "FFmpegError", code: Int(task.terminationStatus), userInfo: nil)
                }
            } catch {
                // Try again with reencoding if copy fails
                print("Falling back to reencoding for \(output)")
                let fallbackTask = Process()
                fallbackTask.executableURL = URL(fileURLWithPath: "/usr/local/bin/ffmpeg")
                fallbackTask.arguments = [
                    "-ss", String(st), "-i", VIDEO_FILE,
                    "-t", String(duration), output
                ]
                
                try fallbackTask.run()
                fallbackTask.waitUntilExit()
            }
        }
    } catch {
        print("Error extracting clips: \(error)")
    }
}

// ---------------------------------------------------------------------------
// Save segments to CSV
// ---------------------------------------------------------------------------
func saveSegmentsToCSV(segments: [(String, Int, Int, String)]) {
    var csvContent = "YouTube ID,Start (s),End (s),Title\n"
    
    for (cid, st, ed, title) in segments {
        // Escape quotes in title
        let escapedTitle = title.replacingOccurrences(of: "\"", with: "\"\"")
        csvContent += "\(cid),\(st),\(ed),\"\(escapedTitle)\"\n"
    }
    
    do {
        try csvContent.write(to: URL(fileURLWithPath: "segments.csv"), atomically: true, encoding: .utf8)
        print("Saved segments.csv")
    } catch {
        print("Error saving CSV: \(error)")
    }
}

// ---------------------------------------------------------------------------
// Main function
// ---------------------------------------------------------------------------
func main() {
    print("=== YouTube Segment Detector (Vision framework + one GPT call per video) ===")
    
    findYoutubeSegments { segments in
        // Filter by minimum duration
        let filteredSegments = segments.filter { (_, st, ed, _) in
            return (ed - st) >= MIN_SEGMENT_DURATION
        }
        
        if filteredSegments.isEmpty {
            print("No segments meet the minimum duration.")
        } else {
            // Print segments
            for (cid, st, ed, title) in filteredSegments {
                let m1 = st / 60
                let s1 = st % 60
                let m2 = ed / 60
                let s2 = ed % 60
                print("ID \(cid): \(m1):\(String(format: "%02d", s1))–\(m2):\(String(format: "%02d", s2)) (Title: \(title))")
            }
            
            // Save CSV
            saveSegmentsToCSV(segments: filteredSegments)
            
            // Extract clips
            extractSegmentClips(segments: filteredSegments)
        }
    }
}

// ---------------------------------------------------------------------------
// String extension for Levenshtein distance calculation
// ---------------------------------------------------------------------------
extension String {
    func levenshteinDistance(to target: String) -> Int {
        let source = self
        let m = source.count
        let n = target.count
        
        if m == 0 { return n }
        if n == 0 { return m }
        
        var matrix = [[Int]](repeating: [Int](repeating: 0, count: n + 1), count: m + 1)
        
        // Initialize first row and column
        for i in 0...m {
            matrix[i][0] = i
        }
        
        for j in 0...n {
            matrix[0][j] = j
        }
        
        // Fill the matrix
        for i in 1...m {
            let sourceIndex = source.index(source.startIndex, offsetBy: i - 1)
            let sourceChar = source[sourceIndex]
            
            for j in 1...n {
                let targetIndex = target.index(target.startIndex, offsetBy: j - 1)
                let targetChar = target[targetIndex]
                
                let cost = sourceChar == targetChar ? 0 : 1
                let aboveCell = matrix[i-1][j] + 1
                let leftCell = matrix[i][j-1] + 1
                let diagonalCell = matrix[i-1][j-1] + cost
                
                matrix[i][j] = min(aboveCell, leftCell, diagonalCell)
            }
        }
        
        return matrix[m][n]
    }
}

// Start the program
main()