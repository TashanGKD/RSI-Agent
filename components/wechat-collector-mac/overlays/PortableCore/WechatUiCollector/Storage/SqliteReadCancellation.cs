using Microsoft.Data.Sqlite;
using SQLitePCL;
using System.Threading;

namespace WechatUiCollector.Storage;

// One registration per owned read connection. Dispose it before the connection;
// cancellation must never interrupt a writer or another operation's connection.
public static class SqliteReadCancellation
{
    public static CancellationTokenRegistration Attach(SqliteConnection connection, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var handle = connection.Handle;
        return token.Register(() => raw.sqlite3_interrupt(handle));
    }
}
