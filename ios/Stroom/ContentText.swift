import Foundation

/// Feed descriptions can mix HTML and Markdown. Never load remote content to clean text.
enum ContentText {
    private static let entities: [String: String] = {
        guard let url = Bundle.main.url(forResource: "HTMLEntities", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let result = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return result
    }()
    private static func replace(_ text: String, _ pattern: String, _ transform: (String, [String]) -> String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        var result = text
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let range = Range(match.range, in: result) else { continue }
            let groups = (1..<match.numberOfRanges).map { Range(match.range(at: $0), in: text).map { String(text[$0]) } ?? "" }
            result.replaceSubrange(range, with: transform(String(text[Range(match.range, in: text)!]), groups))
        }
        return result
    }
    static func decodeEntities(_ raw: String) -> String {
        replace(raw, #"&(#x[0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);"#) { original, groups in
            let name = groups[0]
            if name.hasPrefix("#") {
                let hex = name.lowercased().hasPrefix("#x")
                if let number = UInt32(name.dropFirst(hex ? 2 : 1), radix: hex ? 16 : 10),
                   let scalar = UnicodeScalar(number), number > 0 { return String(scalar) }
                return ""
            }
            return entities[name] ?? original
        }
    }
    static func markdown(_ raw: String) -> String {
        // Decode before stripping: escaped HTML must not become visible markup afterward.
        var text = raw
        for _ in 0..<2 { text = decodeEntities(text) }
        text = text.replacingOccurrences(of: #"(?is)<(script|style|iframe|object|noscript)\b[^>]*>.*?</\1\s*>"#, with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?s)<!--.*?-->"#, with: "", options: .regularExpression)
        text = replace(text, #"(?is)<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a\s*>"#) { _, groups in
            guard let url = URL(string: groups[0]), ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") else { return groups[1] }
            let target = groups[0].replacingOccurrences(of: "(", with: "%28").replacingOccurrences(of: ")", with: "%29")
            return "[\(groups[1])](\(target))"
        }
        text = text.replacingOccurrences(of: #"(?i)<br\s*/?>"#, with: "\n", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?i)</?(p|div|section|article|ul|ol|blockquote|h[1-6]|pre)\b[^>]*>"#, with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?i)<li\b[^>]*>"#, with: "\n• ", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?i)</li\s*>"#, with: "\n", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?i)</?(strong|b)\b[^>]*>"#, with: "**", options: .regularExpression)
        text = text.replacingOccurrences(of: #"(?i)</?(em|i)\b[^>]*>"#, with: "*", options: .regularExpression)
        text = text.replacingOccurrences(of: #"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*?)?\s*/?>"#, with: "", options: .regularExpression)
        return text.replacingOccurrences(of: #"\n[ \t]*\n(?:[ \t]*\n)+"#, with: "\n\n", options: .regularExpression).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    static func excerpt(_ raw: String?) -> String {
        let clean = markdown(raw ?? "")
            .replacingOccurrences(of: #"!\[([^\]]*)\]\([^)]*\)"#, with: "$1", options: .regularExpression)
        // Full Markdown parsing drops paragraph boundaries in characters; parse each
        // source line separately before flattening the excerpt.
        let plain = clean.components(separatedBy: "\n").map { line in
            (try? AttributedString(markdown: line)).map { String($0.characters) } ?? line
        }.joined(separator: " ")
        return plain.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
