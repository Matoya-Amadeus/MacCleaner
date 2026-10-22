import Foundation

/// 极简 JSON 值：内核返回的结构会随版本增字段，用强类型模型会很脆。
/// 需要强类型的地方（`DiskReport` 等）在各自的 View 里再从 `JSONValue` 解出来。
enum JSONValue: Codable, Equatable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "无法识别的 JSON 值")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    // MARK: - 取值（宽容：类型不对就返回 nil，不崩）

    var stringValue: String? {
        switch self {
        case .string(let value): return value
        case .int(let value): return String(value)
        case .double(let value): return String(value)
        default: return nil
        }
    }

    var intValue: Int64? {
        switch self {
        case .int(let value): return Int64(value)
        case .double(let value): return Int64(value)
        case .string(let value): return Int64(value)
        default: return nil
        }
    }

    var doubleValue: Double? {
        switch self {
        case .int(let value): return Double(value)
        case .double(let value): return value
        case .string(let value): return Double(value)
        default: return nil
        }
    }

    var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    subscript(key: String) -> JSONValue? { objectValue?[key] }

    static func from(_ object: [String: Any]) -> JSONValue {
        var mapped: [String: JSONValue] = [:]
        for (key, value) in object { mapped[key] = from(any: value) }
        return .object(mapped)
    }

    private static func from(any value: Any) -> JSONValue {
        switch value {
        case let value as String: return .string(value)
        case let value as Bool: return .bool(value)
        case let value as Int: return .int(value)
        case let value as Double: return .double(value)
        case let value as [Any]: return .array(value.map { from(any: $0) })
        case let value as [String: Any]: return from(value)
        default: return .null
        }
    }
}

/// 字节数统一按十进制显示（1 GB = 1000 MB），与 Finder 一致。
enum ByteText {
    static func format(_ bytes: Int64) -> String {
        // `ByteCountFormatter` 对 0 会输出 "Zero KB"——列表里看着像单位错了。
        guard bytes > 0 else { return "0 B" }
        let formatter = ByteCountFormatter()
        formatter.countStyle = .decimal
        formatter.allowedUnits = [.useKB, .useMB, .useGB, .useTB]
        return formatter.string(fromByteCount: max(0, bytes))
    }
}
