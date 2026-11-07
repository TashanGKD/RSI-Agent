import Foundation

/// A readiness file alone is insufficient: it must name the exact child and launch.
struct BackendIdentity: Decodable {
    let port: Int
    let pid: Int32
    let instanceId: String
    var baseURL: URL { URL(string: "http://127.0.0.1:\(port)")! }

    static func parse(_ data: Data, expectedInstance: String, expectedPID: Int32) -> BackendIdentity? {
        guard let identity = try? JSONDecoder().decode(BackendIdentity.self, from: data),
              !expectedInstance.isEmpty, identity.instanceId == expectedInstance,
              identity.pid == expectedPID, expectedPID > 0, (1...65535).contains(identity.port) else { return nil }
        return identity
    }
    func matchesSession(_ data: Data) -> Bool {
        guard let session = Self.parse(data, expectedInstance: instanceId, expectedPID: pid) else { return false }
        return session.port == port
    }
}
