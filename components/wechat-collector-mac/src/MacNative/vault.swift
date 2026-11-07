import Foundation
import Security

// A stable helper owns the login-keychain item for both the app and CLI.
let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "local.wechat.collector.mac", kSecAttrAccount as String: "archive-master-key-v1", kSecAttrSynchronizable as String: false]
func readKey() throws -> Data? {
    var query = base; query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = result as? Data, data.count == 32 else { throw NSError(domain: "MacVault", code: Int(status)) }
    return data
}
do {
    var key = try readKey()
    if key == nil {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw NSError(domain: "MacVault", code: -1) }
        var entry = base; entry[kSecValueData as String] = Data(bytes); entry[kSecAttrLabel as String] = "微信记录：本地凭证加密"
        let status = SecItemAdd(entry as CFDictionary, nil)
        guard status == errSecSuccess || status == errSecDuplicateItem else { throw NSError(domain: "MacVault", code: Int(status)) }
        key = try readKey()
        bytes.withUnsafeMutableBytes { buffer in buffer.initializeMemory(as: UInt8.self, repeating: 0) }
    }
    guard let key = key else { throw NSError(domain: "MacVault", code: -1) }
    FileHandle.standardOutput.write(key)
} catch {
    FileHandle.standardError.write(Data("钥匙串暂不可用，请解锁电脑后重试。\n".utf8))
    exit(1)
}
