using System.Text.Json;
using System.Security.Cryptography;
using WechatCollector.Mac;
using WechatUiCollector.Storage;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;

var project = Path.GetFullPath(Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.Combine(AppContext.BaseDirectory, "../../../../../"));
var state = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Application Support/WechatCollectorMac");
var legacyArchive = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Application Support/LocalWeChatReader");
var startup = HostStartupPaths.Resolve(state, legacyArchive);
state = startup.StateDirectory;
using var localImports = new MacImportProvider(state, startup.ArchivePath);
WechatUiCollector.WechatDb.WechatLocalImportProviders.Register(localImports);
Directory.CreateDirectory(state); File.SetUnixFileMode(state, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
var loggingOptions = File.Exists(Path.Combine(state, "settings.json"))
    ? ConfigurationLoader.LoadOptions(Path.Combine(state, "settings.json"))
    : ConfigurationLoader.LoadDefaultOptions() with { LogDirectory = Path.Combine(state, "logs") };
using var appLogger = AppLoggerFactory.Create(loggingOptions, state, writeToConsole: false);
RuntimeEventSource.Configure(appLogger);
RuntimeEventSource.Emit(AppLogLevel.Information, "MAC_HOST_STARTING", "MacHost", "正在准备本地服务。");
var store = new SqliteMessageStore(startup.DatabasePath, startup.BackupRetentionCount);
await store.InitializeAsync(CancellationToken.None);
var archive = startup.ArchivePath;
if (args.Contains("--import"))
{
    long previous = 0;
    var count = await new MacArchiveImport(store, archive).RunAsync((count, source) => { if (count - previous >= 100000) { Console.WriteLine(JsonSerializer.Serialize(new { rowsProcessed = count, source })); previous = count; } }, CancellationToken.None);
    Console.WriteLine(JsonSerializer.Serialize(new { status = "complete", rowsProcessed = count })); return;
}
if (args.Contains("--voice-model"))
{
    await new WechatUiCollector.WechatDb.VoiceModelManager().EnsureAsync(null, CancellationToken.None);
    Console.WriteLine(JsonSerializer.Serialize(new { status = (await new WechatUiCollector.WechatDb.VoiceModelManager().CheckAsync(CancellationToken.None)).State })); return;
}
if (args.Contains("--check")) { Console.WriteLine(JsonSerializer.Serialize(new { integrity = await store.CheckIntegrityAsync(CancellationToken.None) })); return; }
// Native launches supply a fresh secret and identity through the private child environment.
// No persistent token/entry file is reused across application launches.
var launchSecret = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_BRIDGE_SECRET");
var instanceId = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_INSTANCE") ?? Guid.NewGuid().ToString("N");
var readyFile = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_READY_FILE");
if (readyFile is not null && (string.IsNullOrWhiteSpace(launchSecret) || string.IsNullOrWhiteSpace(instanceId)))
    throw new InvalidOperationException("Incomplete native launch identity.");
var secret = launchSecret ?? Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
int port = 0;
var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.UseUrls($"http://127.0.0.1:{port}");
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 1024 * 1024);
var app = builder.Build();
var assetsRoot = Path.Combine(project, "reference-web");
var assets = Directory.EnumerateFiles(assetsRoot, "*", SearchOption.AllDirectories).ToDictionary(file => "/" + Path.GetRelativePath(assetsRoot, file), StringComparer.Ordinal);
foreach (var file in Directory.EnumerateFiles(Path.Combine(assetsRoot, "assets/fonts")))
{
    var alias = Path.GetFileNameWithoutExtension(file).Split('-');
    var family = alias[0] == "misans" ? "MiSans" : "JetBrainsMono";
    string weight = alias[1] switch { "regular" => "Regular", "medium" => "Medium", "bold" => "Bold", _ => family == "MiSans" ? "Semibold" : "SemiBold" };
    assets[$"/fonts/{family}-{weight}.ttf"] = file;
}
var controller = new MacController(store, state, archive, appLogger as IRecentLogSource);
app.Lifetime.ApplicationStopping.Register(controller.RequestStop);
app.Use(async (context, next) =>
{
    context.Response.Headers["Cache-Control"] = "no-store";
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["Referrer-Policy"] = "no-referrer";
    if (!BridgeSecurity.LocalHost(context.Request.Host.Value, port) || !BridgeSecurity.SameOrigin(context.Request.Headers.Origin, port)) { context.Response.StatusCode = 403; return; }
    string? presented = context.Request.Headers.Authorization.ToString();
    if (presented?.StartsWith("Bearer ", StringComparison.Ordinal) == true) presented = presented[7..]; else presented = context.Request.Cookies["collector-session"];
    if (!BridgeSecurity.EqualToken(presented, secret))
    {
        if (context.Request.Path == "/" && context.Request.Method == "GET") { context.Response.ContentType = "text/html; charset=utf-8"; await context.Response.WriteAsync(File.ReadAllText(Path.Combine(project, "src/MacHost/Web/login.html"))); return; }
        context.Response.StatusCode = 401; return;
    }
    if (context.Request.Headers.Authorization.Count > 0)
        context.Response.Cookies.Append("collector-session", secret, new CookieOptions { HttpOnly = true, SameSite = SameSiteMode.Strict, IsEssential = true });
    await next();
});
app.MapPost("/session", (HttpContext context) => BridgeSecurity.SameInstance(context.Request.Headers["X-Collector-Instance"], instanceId)
    ? Results.Json(new { connected = true, port, pid = Environment.ProcessId, instanceId })
    : Results.StatusCode(403));
app.MapGet("/events/{page}", (string page) => Results.Json(controller.Drain(page)));
app.MapGet("/preview/{id}", IResult (string id) =>
{
    if (controller.IsStickerResource(id)) return controller.ReadStickerResource(id) is { } sticker ? Results.Bytes(sticker.Bytes, sticker.Mime) : Results.NotFound();
    return controller.MediaResource(id) is { } resource ? Results.File(resource.Path, resource.Mime, enableRangeProcessing: true) : Results.NotFound();
});
app.MapGet("/avatar/{id}", async (string id, CancellationToken token) => await controller.ReadAvatarResourceAsync(id, token) is { } avatar ? Results.Bytes(avatar.Bytes, avatar.ContentType) : Results.NotFound());
app.MapPost("/native/vision", async (HttpContext context, JsonElement command, CancellationToken token) =>
{
    if (!BridgeSecurity.EqualToken(context.Request.Headers.Authorization.ToString(), "Bearer " + secret) || !BridgeSecurity.SameInstance(context.Request.Headers["X-Collector-Instance"], instanceId)) return Results.StatusCode(403);
    try { return Results.Json(await controller.ReadVisionStatusAsync(command.GetRawText(), token)); }
    catch (ArgumentException) { return Results.BadRequest(new { status = "blocked", message = "窗口读取结果无效，未执行操作。" }); }
});
app.MapPost("/native/connection", async (HttpContext context, JsonElement command, CancellationToken token) =>
{
    if (!BridgeSecurity.EqualToken(context.Request.Headers.Authorization.ToString(), "Bearer " + secret) || !BridgeSecurity.SameInstance(context.Request.Headers["X-Collector-Instance"], instanceId)) return Results.StatusCode(403);
    try { return Results.Json(await controller.NativeConnectionAsync(command.GetRawText(), token)); }
    catch (Exception error) when (error is ArgumentException or JsonException) { return Results.BadRequest(new { status = "blocked", message = "连接请求已过期，未执行操作。" }); }
});
app.MapPost("/bridge/{page}", async (string page, JsonElement command, CancellationToken token) =>
{
    if (!MacController.Pages.Contains(page)) return Results.BadRequest();
    await controller.HandleAsync(page, command, token, drainEvents: false);
    return Results.Json(new { accepted = true });
});
app.MapGet("/host.js", () => Results.Text(File.ReadAllText(Path.Combine(project, "src/MacHost/Web/host.js")), "text/javascript; charset=utf-8"));
app.MapGet("/", () => Results.Text(File.ReadAllText(Path.Combine(project, "src/MacHost/Web/shell.html")), "text/html; charset=utf-8"));
app.MapGet("/{**path}", async (HttpContext context, string path) =>
{
    var file = BridgeSecurity.Asset("/" + path, assets);
    if (file is null) { context.Response.StatusCode = 404; return; }
    var extension = Path.GetExtension(file);
    context.Response.ContentType = extension switch { ".html" => "text/html; charset=utf-8", ".js" => "text/javascript; charset=utf-8", ".css" => "text/css; charset=utf-8", ".ttf" => "font/ttf", ".png" => "image/png", _ => "application/octet-stream" };
    if (extension is ".html" or ".css" or ".js")
    {
        var content = (await File.ReadAllTextAsync(file)).Replace("https://wechat.local/", "/");
        if (extension == ".html") content = content.Replace("<head>", "<head><script src=\"/host.js\"></script>");
        await context.Response.WriteAsync(content);
    }
    else await context.Response.SendFileAsync(file);
});
// Publish readiness only after Kestrel actually owns the randomly assigned loopback port.
try
{
await app.StartAsync();
port = new Uri(app.Urls.Single()).Port;
RuntimeEventSource.Emit(AppLogLevel.Information, "MAC_HOST_READY", "MacHost", "本地服务已启动。");
var readiness = JsonSerializer.Serialize(new { port, pid = Environment.ProcessId, instanceId });
if (readyFile is not null)
{
    var temporary = readyFile + ".tmp";
    File.WriteAllText(temporary, readiness);
    File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite);
    File.Move(temporary, readyFile, overwrite: true);
}
else Console.WriteLine(readiness);
await app.WaitForShutdownAsync();
}
finally
{
    controller.RequestStop();
    if (!await controller.WaitForStopAsync(TimeSpan.FromSeconds(20)))
        RuntimeEventSource.Emit(AppLogLevel.Warning, "MAC_SHUTDOWN_TIMEOUT", "MacHost", "后台任务未在退出宽限期内全部结束；已请求取消并停止本应用工作进程。");
    RuntimeEventSource.Reset();
}
