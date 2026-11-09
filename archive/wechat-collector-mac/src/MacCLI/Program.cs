using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FlaUI.Core.AutomationElements;
using WechatUiCollector.Automation;
using WechatUiCollector.Cli;
using WechatUiCollector.Collection;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.Models;
using WechatUiCollector.OfficialAccount;
using WechatUiCollector.Output;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;
using WechatCollector.Mac;

[CompilerGenerated]
internal class Program
{
	public static async Task<int> Main(string[] args)
	{
		AgentJobs.ConfigureWorkerEntryPoint(Environment.ProcessPath ?? throw new InvalidOperationException("无法定位 CLI 可执行文件。"), typeof(Program).Assembly.Location);
		DpiAwareness.ConfigurePerMonitorV2();
		CliConsole.ConfigureUtf8();
		CliInvocation invocation;
		try
		{
			invocation = CliInvocationParser.Parse(args);
		}
		catch (CliUsageException ex)
		{
			Console.Error.WriteLine(ex.Message);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "invalidArguments", ex.Message);
			}
			return 2;
		}
		if (!OperatingSystem.IsWindows() && !OperatingSystem.IsMacOS())
		{
			Console.Error.WriteLine("该采集器仅支持 Windows 与 macOS。");
			return 3;
		}
		if (invocation.ShowVersion)
		{
			Console.WriteLine(CliVersion.Get());
			return 0;
		}
		if (invocation.ShowHelp)
		{
			Console.WriteLine(invocation.Json ? CliHelpText.RenderJson(invocation.HelpTarget) : CliHelpText.Render(invocation.HelpTarget));
			return 0;
		}
		if ((object)invocation.Descriptor == null)
		{
			string text = "未知命令：" + invocation.Command + "。使用 -h 查看规范命令。";
			Console.Error.WriteLine(text);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "unknownCommand", text);
			}
			return 2;
		}
		string logLevel = invocation.LogLevel;
		if (logLevel != null && !Enum.TryParse<AppLogLevel>(logLevel, ignoreCase: true, out var _))
		{
			string text2 = $"--log-level 无效：{logLevel}。可选：{string.Join("、", Enum.GetNames<AppLogLevel>())}。";
			Console.Error.WriteLine(text2);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "invalidArguments", text2);
			}
			return 2;
		}
		string command = invocation.Command;
		MacImportProvider macImports = null;
		try { if (OperatingSystem.IsMacOS()) macImports = ConfigureMacImports(); }
		catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException or JsonException)
		{
			const string message = "无法加载 Mac 本地导入配置，请检查 --settings 路径和内容。";
			Console.Error.WriteLine(message);
			if (invocation.Json) CliErrorEnvelope.Write(Console.Out, "invalidConfiguration", message);
			return 2;
		}
		using var macImportLifetime = macImports;
		string databaseOverride = invocation.Database;
		IAppLogger appLogger = null;
		MacImportProvider ConfigureMacImports()
		{
			var runtimeProject = MacCliStartup.ResolveRuntimeProject(AppContext.BaseDirectory, Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT"));
			if (runtimeProject is not null) Environment.SetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT", runtimeProject);
			invocation = invocation with { Settings = MacCliStartup.InheritWorkerSettings(invocation.Settings, Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_SETTINGS_PATH")) };
			var settings = CliSettings.Resolve(invocation.Settings);
			var configured = MacCliStartup.LoadOptions(settings);
			var sourceRoot = string.IsNullOrWhiteSpace(configured.AttachmentSourceDirectory) ? null : ConfigurationLoader.ResolvePath(configured.AttachmentSourceDirectory, Path.GetDirectoryName(settings));
			var provider = new MacImportProvider(Path.GetDirectoryName(settings)!, sourceRoot: sourceRoot);
			WechatLocalImportProviders.Register(provider);
			AgentJobs.ConfigureWorkerSettingsPath(settings);
			return provider;
		}
		if (invocation.NoInteraction && invocation.InteractionLevel == CliInteractionLevel.Interacts)
		{
			string text3 = "命令 " + command + " 必然操作微信（点击控件、切换会话或占用鼠标键盘），与 --no-interaction 冲突。请改用只读命令，或去掉 --no-interaction。";
			Console.Error.WriteLine(text3);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "interactionNotAllowed", text3);
			}
			return 3;
		}
		if (invocation.Json && invocation.JsonSupport == CliJsonSupport.Unsupported)
		{
			string text4 = "命令 " + command + " 不支持 --json，请移除该选项或使用支持 JSON 的命令。";
			Console.Error.WriteLine(text4);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "jsonUnsupported", text4);
			}
			return 2;
		}
		switch (command)
		{
		case "changes list":
		case "articles get":
		case "messages assets":
		case "changes prune":
		case "db upgrade":
		case "db reparse":
		case "jobs start":
		case "jobs get":
		case "jobs run":
		case "jobs resume":
		case "jobs cancel":
		case "messages bind-asset":
		case "jobs list":
		{
			CancellationTokenSource agentCancellation = new CancellationTokenSource();
			try
			{
				ConsoleCancelEventHandler cancelAgent = delegate(object? _, ConsoleCancelEventArgs e)
				{
					e.Cancel = true;
					agentCancellation.Cancel();
				};
				Console.CancelKeyPress += cancelAgent;
				try
				{
					return await CliDiagnostics.RunAsync(invocation, () => AgentCommand.ExecuteAsync(invocation, Console.Out, agentCancellation.Token));
				}
				finally
				{
					Console.CancelKeyPress -= cancelAgent;
				}
			}
			finally
			{
				if (agentCancellation != null)
				{
					((IDisposable)agentCancellation).Dispose();
				}
			}
		}
		case "messages image":
		{
			CancellationTokenSource imageCancellation = new CancellationTokenSource();
			try
			{
				ConsoleCancelEventHandler cancelAgent = delegate(object? _, ConsoleCancelEventArgs e)
				{
					e.Cancel = true;
					imageCancellation.Cancel();
				};
				Console.CancelKeyPress += cancelAgent;
				try
				{
					return await CliDiagnostics.RunAsync(invocation, () => MessageImageCommand.ExecuteAsync(invocation, Console.Out, imageCancellation.Token));
				}
				finally
				{
					Console.CancelKeyPress -= cancelAgent;
				}
			}
			finally
			{
				if (imageCancellation != null)
				{
					((IDisposable)imageCancellation).Dispose();
				}
			}
		}
		case "voice search":
		case "voice delete":
		case "voice model":
		case "voice transcribe":
		{
			CancellationTokenSource voiceCancellation = new CancellationTokenSource();
			try
			{
				ConsoleCancelEventHandler cancelAgent = delegate(object? _, ConsoleCancelEventArgs e)
				{
					e.Cancel = true;
					voiceCancellation.Cancel();
				};
				Console.CancelKeyPress += cancelAgent;
				try
				{
					return await CliDiagnostics.RunAsync(invocation, () => VoiceCommand.ExecuteAsync(invocation, Console.Out, voiceCancellation.Token));
				}
				finally
				{
					Console.CancelKeyPress -= cancelAgent;
				}
			}
			finally
			{
				if (voiceCancellation != null)
				{
					((IDisposable)voiceCancellation).Dispose();
				}
			}
		}
		case "content changes":
		case "content index":
		case "content get":
		case "content search":
		case "content status":
		case "content verify":
		{
			CancellationTokenSource cancellation2 = new CancellationTokenSource();
			try
			{
				ConsoleCancelEventHandler cancelAgent = delegate(object? _, ConsoleCancelEventArgs e)
				{
					e.Cancel = true;
					cancellation2.Cancel();
				};
				Console.CancelKeyPress += cancelAgent;
				try
				{
					return await CliDiagnostics.RunAsync(invocation, () => KnowledgeCommand.ExecuteAsync(invocation, Console.Out, cancellation2.Token));
				}
				finally
				{
					Console.CancelKeyPress -= cancelAgent;
				}
			}
			finally
			{
				if (cancellation2 != null)
				{
					((IDisposable)cancellation2).Dispose();
				}
			}
		}
		case "capabilities":
		case "messages get":
		case "messages search":
		case "people search":
		case "chats members":
		case "accounts list":
		case "people get":
		case "chats list":
		case "messages context":
		{
			CancellationTokenSource readCancellation = new CancellationTokenSource();
			try
			{
				ConsoleCancelEventHandler cancelAgent = delegate(object? _, ConsoleCancelEventArgs e)
				{
					e.Cancel = true;
					readCancellation.Cancel();
				};
				Console.CancelKeyPress += cancelAgent;
				try
				{
					return await CliDiagnostics.RunAsync(invocation, () => LocalRecordsCommand.ExecuteAsync(invocation, Console.Out, readCancellation.Token));
				}
				finally
				{
					Console.CancelKeyPress -= cancelAgent;
				}
			}
			finally
			{
				if (readCancellation != null)
				{
					((IDisposable)readCancellation).Dispose();
				}
			}
		}
		default:
			try
			{
				string text5 = CliSettings.Resolve(invocation.Settings);
				AppOptions appOptions;
				WeChatUiProfile profile;
				try
				{
					appOptions = OperatingSystem.IsMacOS() ? MacCliStartup.LoadOptions(text5) : ConfigurationLoader.LoadOptions(text5);
					string path = ConfigurationLoader.ResolvePath(invocation.Profile ?? appOptions.ProfilePath, Path.GetDirectoryName(text5));
					profile = ((string.IsNullOrWhiteSpace(appOptions.ProfilePath) || invocation.InteractionLevel != CliInteractionLevel.None || invocation.Profile != null || File.Exists(path)) ? ConfigurationLoader.Load(text5, invocation.Profile).Profile : new WeChatUiProfile());
				}
				catch (Exception ex2) when (((ex2 is JsonException || ex2 is IOException || ex2 is UnauthorizedAccessException) ? 1 : 0) != 0)
				{
					Console.Error.WriteLine("无法加载配置 " + text5 + "：" + ex2.Message);
					return 2;
				}
				string settingsDirectory = Path.GetDirectoryName(text5);
				AppOptions options = ApplyCliOverrides(appOptions, invocation);
				appLogger = AppLoggerFactory.Create(options, settingsDirectory, !invocation.Quiet);
				UiAutomationFailureAggregator.Configure(appLogger, TimeSpan.FromSeconds(Math.Max(1, options.UiAutomationFailureLogIntervalSeconds)));
				RuntimeEventSource.Configure(appLogger);
				if (invocation.AllowInteraction && !appOptions.AllowWeChatInteraction)
				{
					appLogger.Log(AppLogLevel.Warning, "INTERACTION_ENABLED_BY_CLI", "Program", "本次调用通过 --allow-interaction 授权操作微信；配置中的 AllowWeChatInteraction 为关闭。");
				}
				else if (invocation.NoInteraction && appOptions.AllowWeChatInteraction)
				{
					appLogger.Log(AppLogLevel.Warning, "INTERACTION_DISABLED_BY_CLI", "Program", "本次调用通过 --no-interaction 强制只读；配置中的 AllowWeChatInteraction 为开启。");
				}
				appLogger.Log(AppLogLevel.Information, "APPLICATION_STARTED", "Program", "命令行程序已启动。", new Dictionary<string, object>
				{
					["command"] = command.ToLowerInvariant(),
					["interactionLevel"] = invocation.InteractionLevel.ToString(),
					["allowWeChatInteraction"] = options.AllowWeChatInteraction,
					["quiet"] = invocation.Quiet,
					["jsonRequested"] = invocation.Json
				});
				CancellationTokenSource cancellation = new CancellationTokenSource();
				try
				{
					Console.CancelKeyPress += delegate(object? _, ConsoleCancelEventArgs eventArgs)
					{
						eventArgs.Cancel = true;
						cancellation.Cancel();
					};
					int num5;
					switch (command.ToLowerInvariant())
					{
					case "capture run":
					{
						string databasePath4 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						string path3 = ConfigurationLoader.ResolvePath(options.JsonlOutputPath, settingsDirectory);
						string text14 = ReadOption(args, "--for");
						TimeSpan? runBound = ((text14 == null) ? ((TimeSpan?)null) : new TimeSpan?(ParseDuration(text14, "--for")));
						string text15 = ReadOption(args, "--max-messages");
						int? obj;
						if (text15 != null)
						{
							if (!int.TryParse(text15, out var result5) || result5 < 1 || result5 > 10000000)
							{
								throw new ArgumentException("--max-messages 必须在 1 到 10000000 之间。");
							}
							obj = result5;
						}
						else
						{
							obj = null;
						}
						int? maximumWrittenMessages = obj;
						bool stopAfterFirstCycle = CliOptionReader.IsPresent(args, "--once");
						CollectorRunBounds runBounds = CollectorRunBounds.Create(maximumWrittenMessages, stopAfterFirstCycle);
						AppOptions appOptions2 = options with
						{
							DatabasePath = databasePath4,
							AvatarCatalogPath = ConfigurationLoader.ResolvePath(options.AvatarCatalogPath, settingsDirectory),
							EnableWindowMessageClickFallbackForWhitelist = (options.EnableWindowMessageClickFallbackForWhitelist || args.Contains<string>("--experimental-window-message-fallback", StringComparer.OrdinalIgnoreCase))
						};
						CollectorRunner runner = new CollectorRunner(appOptions2, profile, new SqliteMessageStore(databasePath4, options.BackupRetentionCount), new JsonLinePublisher(path3), appLogger, null, runBounds);
						if (options.AllowWeChatInteraction && options.EnableMonitoredConversationOpening)
						{
							if (options.MonitoredConversationWhitelist.Length == 0)
							{
								appLogger.Log(AppLogLevel.Warning, "AUTOOPEN_WHITELIST_EMPTY", "Program", "会话摘要变化采集已开启，但已选择会话为空；程序不会切换任何会话。");
							}
							else
							{
								appLogger.Log(AppLogLevel.Warning, "AUTOOPEN_ENABLED", "Program", "已选择会话的摘要变化采集已开启；精确打开目标可能改变其已读状态。", new Dictionary<string, object>
								{
									["whitelistCount"] = options.MonitoredConversationWhitelist.Length,
									["mouseFallbackEnabled"] = options.EnableMouseClickFallbackForWhitelist,
									["windowMessageFallbackEnabled"] = appOptions2.EnableWindowMessageClickFallbackForWhitelist
								});
								if (appOptions2.EnableWindowMessageClickFallbackForWhitelist)
								{
									appLogger.Log(AppLogLevel.Warning, "WINDOW_MESSAGE_FALLBACK_ENABLED", "Program", "实验性窗口消息切换已开启；检测到焦点或窗口层级变化时将自动熔断。");
								}
								if (options.EnableMouseClickFallbackForWhitelist)
								{
									appLogger.Log(AppLogLevel.Warning, "MOUSE_FALLBACK_ENABLED", "Program", "真实鼠标点击兜底已开启，仅允许用于精确白名单会话。");
								}
							}
						}
						if (options.AllowWeChatInteraction && options.EnableMergedForwardExpansion)
						{
							appLogger.Log(AppLogLevel.Warning, "MERGED_FORWARD_EXPANSION_ENABLED", "Program", "合并转发自动解析已开启；程序只会在精确白名单会话中打开卡片、读取独立窗口并关闭。", new Dictionary<string, object>
							{
								["whitelistCount"] = options.MergedForwardConversationWhitelist.Length,
								["maximumCardsPerBatch"] = options.MergedForwardMaximumCardsPerBatch
							});
						}
						if (!options.AllowWeChatInteraction)
						{
							appLogger.Log(AppLogLevel.Information, "READ_ONLY_MODE_ENABLED", "Program", "只读采集已启动：不点击、不发送、不切换会话。");
						}
						Console.Error.WriteLine("按 Ctrl+C 停止。");
						using CancellationTokenSource boundCancellation = ((!runBound.HasValue) ? null : new CancellationTokenSource(runBound.Value));
						if (boundCancellation != null)
						{
							Console.Error.WriteLine($"已设置时长上限 {runBound.Value}；到达后按安全点停止，断点与游标可续传。");
						}
						if ((object)runBounds != null)
						{
							TextWriter error = Console.Error;
							int? maximumWrittenMessages2 = runBounds.MaximumWrittenMessages;
							object value6;
							if (maximumWrittenMessages2.HasValue)
							{
								int valueOrDefault = maximumWrittenMessages2.GetValueOrDefault();
								value6 = $"已设置条数上限 {valueOrDefault} 条新消息；到达后按安全点停止，可续传。";
							}
							else
							{
								value6 = "已设置 --once：完成一个观察周期后按安全点停止。";
							}
							error.WriteLine((string?)value6);
						}
						using CancellationTokenSource linkedCancellation = ((boundCancellation == null) ? null : CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token, boundCancellation.Token));
						_ = 5;
						try
						{
							await runner.RunAsync(linkedCancellation?.Token ?? cancellation.Token);
						}
						catch (OperationCanceledException) when (boundCancellation?.IsCancellationRequested ?? false)
						{
						}
						if (boundCancellation != null && boundCancellation.IsCancellationRequested)
						{
							appLogger.Log(AppLogLevel.Information, "COLLECTOR_RUN_BOUND_REACHED", "Program", "采集已到达 --for 时长上限并按安全点停止。", new Dictionary<string, object> { ["boundSeconds"] = (int)runBound.Value.TotalSeconds });
							Console.WriteLine("已达 --for 时长上限，采集按安全点停止；断点与游标已保存，可续传。");
						}
						if (runner.StopReason != CollectorRunStopReason.NotStopped)
						{
							Console.WriteLine($"采集已按设定边界停止（{runner.StopReason}），累计写入 {runner.WrittenMessageCount} 条新消息；" + "断点与游标已保存，可续传。");
						}
						if (WantsJson(args, invocation, "capture run"))
						{
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								writtenMessageCount = runner.WrittenMessageCount,
								stopReason = runner.StopReason.ToString(),
								timeBoundReached = (boundCancellation?.IsCancellationRequested ?? false),
								timeBoundSeconds = (int?)runBound?.TotalSeconds,
								requestedBounds = (((object)runBounds == null) ? null : new
								{
									maximumWrittenMessages = runBounds.MaximumWrittenMessages,
									stopAfterFirstCycle = runBounds.StopAfterFirstCycle
								}),
								allowWeChatInteraction = options.AllowWeChatInteraction,
								cancelled = false
							}, CliJson.Options));
						}
						return 0;
					}
					case "debug ui-tree":
					{
						string path4 = ReadOption(args, "--output") ?? "ui-tree.txt";
						string outputPath = ConfigurationLoader.ResolvePath(path4);
						string directoryName2 = Path.GetDirectoryName(outputPath);
						if (!string.IsNullOrEmpty(directoryName2))
						{
							ProtectedFileSystem.CreateDirectory(directoryName2);
						}
						using WeChatAutomationSession session = AttachWeChat(profile);
						await using (FileStream stream = new FileStream(ProtectedFileSystem.OpenPath(outputPath, FileAccess.Write), FileMode.Create, FileAccess.Write, FileShare.Read))
						{
							int num6;
							await using (StreamWriter writer = new StreamWriter(stream))
							{
								await UiTreeDumper.DumpAsync(session.Window, writer, options.InspectionMaxDepth, options.InspectionMaxChildrenPerNode, cancellation.Token);
								if (WantsJson(args, invocation, "debug ui-tree"))
								{
									Console.WriteLine(JsonSerializer.Serialize(new
									{
										path = outputPath,
										maxDepth = options.InspectionMaxDepth,
										maxChildrenPerNode = options.InspectionMaxChildrenPerNode
									}, CliJson.Options));
								}
								else
								{
									Console.WriteLine("UI 树已写入：" + outputPath);
								}
								num6 = 0;
							}
							num5 = num6;
						}
						return num5;
					}
					case "debug snapshot":
					{
						using WeChatAutomationSession weChatAutomationSession = AttachWeChat(profile);
						Console.WriteLine(JsonSerializer.Serialize(new MessageSnapshotReader(profile).Read(weChatAutomationSession.Window), CliJson.Options));
						return 0;
					}
					case "sessions list":
					{
						bool flag5 = CliOptionReader.IsPresent(args, "--all-pages");
						string text36 = ReadOption(args, "--max-pages");
						int num12;
						if (text36 != null)
						{
							if (!int.TryParse(text36, out var result23) || result23 < 1 || result23 > 200)
							{
								throw new ArgumentException("--max-pages 必须在 1 到 200 之间。");
							}
							num12 = result23;
						}
						else
						{
							num12 = 30;
						}
						int num13 = num12;
						bool includePreview = CliOptionReader.IsPresent(args, "--include-preview");
						string text37 = ResolveOutputFormat(args, invocation, "table");
						if ((!(text37 == "table") && !(text37 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + text37 + "。可选：table、json。");
						}
						Console.Error.WriteLine(flag5 ? $"正在读取微信会话列表（最多 {num13} 页；只读，不点击、不切换会话）…" : "正在读取微信首屏会话列表（只读，不点击、不切换会话；加 --all-pages 翻页读取全部）…");
						SessionListReadResult readResult;
						using (WeChatAutomationSession weChatAutomationSession2 = AttachWeChat(profile))
						{
							SessionListReader sessionListReader = new SessionListReader(profile);
							readResult = (flag5 ? sessionListReader.ReadAllPagesDetailed(weChatAutomationSession2.Window, num13, 120, cancellation.Token) : sessionListReader.ReadDetailed(weChatAutomationSession2.Window));
						}
						appLogger.Log((readResult.Outcome == SessionListReadOutcome.Ok) ? AppLogLevel.Information : AppLogLevel.Warning, "CLI_SESSIONS_LISTED", "Program", "已读取微信会话列表。", new Dictionary<string, object>
						{
							["outcome"] = readResult.Outcome.ToString(),
							["sessionCount"] = readResult.Snapshot.Sessions.Count,
							["matchedElementCount"] = readResult.MatchedElementCount,
							["parsedItemCount"] = readResult.ParsedItemCount,
							["allPages"] = flag5,
							["includePreview"] = includePreview
						});
						var value11 = new
						{
							observedAt = readResult.Snapshot.ObservedAt,
							outcome = readResult.Outcome.ToString(),
							allPages = flag5,
							matchedElementCount = readResult.MatchedElementCount,
							parsedItemCount = readResult.ParsedItemCount,
							count = readResult.Snapshot.Sessions.Count,
							sessions = readResult.Snapshot.Sessions.Select((ObservedSession observedSession) => new
							{
								conversation = observedSession.Conversation,
								unreadCount = observedSession.UnreadCount,
								displayTimestamp = observedSession.DisplayTimestamp,
								isPinned = observedSession.IsPinned,
								isMuted = observedSession.IsMuted,
								sender = (includePreview ? observedSession.Sender : null),
								preview = (includePreview ? observedSession.Preview : null)
							}).ToArray()
						};
						string text38 = ((text37 == "json") ? JsonSerializer.Serialize(value11, CliJson.Options) : string.Join(Environment.NewLine, readResult.Snapshot.Sessions.Select((ObservedSession observedSession) => observedSession.Conversation)));
						string text39 = ReadOption(args, "--output");
						if (text39 == null)
						{
							Console.WriteLine(text38);
						}
						else
						{
							string outputPath = ConfigurationLoader.ResolvePath(text39);
							string directoryName7 = Path.GetDirectoryName(outputPath);
							if (!string.IsNullOrEmpty(directoryName7))
							{
								ProtectedFileSystem.CreateDirectory(directoryName7);
							}
							await ProtectedFileSystem.WriteAllTextAsync(outputPath, text38, cancellation.Token);
							Console.WriteLine($"已输出 {readResult.Snapshot.Sessions.Count} 个会话：{outputPath}");
						}
						Console.Error.WriteLine($"共 {readResult.Snapshot.Sessions.Count} 个会话（结局 {readResult.Outcome}，匹配元素 {readResult.MatchedElementCount}，解析条目 {readResult.ParsedItemCount}）。");
						return readResult.Outcome switch
						{
							SessionListReadOutcome.Ok => 0, 
							SessionListReadOutcome.NoVisibleItems => 0, 
							_ => 3, 
						};
					}
					case "capture backfill":
					{
						string conversation = ReadOption(args, "--conversation") ?? throw new ArgumentException("capture backfill 必须提供 --conversation 精确会话名称。");
						string databasePath12 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						string path5 = ConfigurationLoader.ResolvePath(options.JsonlOutputPath, settingsDirectory);
						string text25 = ReadOption(args, "--max-pages");
						AppOptions appOptions3;
						if (text25 != null)
						{
							if (!int.TryParse(text25, out var result14) || result14 < 1 || result14 > 100)
							{
								throw new ArgumentException("--max-pages 必须在 1 到 100 之间。");
							}
							appOptions3 = options with { HistoryBackfillMaximumPages = result14 };
						}
						else
						{
							appOptions3 = options;
						}
						Console.WriteLine("安全历史回填：程序先通过 UI Automation 打开目标；UIA 动作无效时会精确点击唯一白名单会话兜底，不使用搜索框或键盘；按 Ctrl+C 可取消。");
						Progress<BackfillProgress> progress2 = new Progress<BackfillProgress>(delegate(BackfillProgress backfillProgress)
						{
							Console.Error.WriteLine($"页数={backfillProgress.PagesRead} 新增={backfillProgress.MessagesWritten} 状态={backfillProgress.Status}");
						});
						BackfillResult backfillResult = await new HistoryBackfillRunner(appOptions3, profile, new SqliteMessageStore(databasePath12, options.BackupRetentionCount), new JsonLinePublisher(path5), appLogger).RunAsync(conversation, progress2, cancellation.Token);
						if (WantsJson(args, invocation, "capture backfill"))
						{
							Console.WriteLine(JsonSerializer.Serialize(backfillResult, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"回填结束：{backfillResult.StopReason}，读取 {backfillResult.PagesRead} 页，新增 {backfillResult.MessagesWritten} 条。");
						}
						int result15;
						switch (backfillResult.StopReason)
						{
						case BackfillStopReason.Cancelled:
							result15 = 130;
							break;
						case BackfillStopReason.ConversationChanged:
						case BackfillStopReason.WindowUnavailable:
							result15 = 3;
							break;
						case BackfillStopReason.Failed:
							result15 = 1;
							break;
						default:
							result15 = 0;
							break;
						}
						return result15;
					}
					case "articles backfill":
					{
						string biz5 = ReadOption(args, "--biz") ?? throw new ArgumentException("articles backfill 必须提供 --biz（公众号 __biz，见任一文章 URL 的 __biz 参数）。");
						string text26 = ReadOption(args, "--key");
						string text27 = ReadOption(args, "--uin");
						string passTicket = ReadOption(args, "--pass-ticket");
						ProfileExtCredentials credentials2;
						if (text26 == null && text27 == null)
						{
							ProfileExtCredentials profileExtCredentials = new ProfileExtCredentialStore().TryLoad(biz5);
							if ((object)profileExtCredentials == null)
							{
								throw new ArgumentException("未提供 --key/--uin，且本地没有该公众号的已保存凭证。请先执行 official harvest 捕获凭证，或同时提供 --key 与 --uin。");
							}
							credentials2 = profileExtCredentials;
							Console.Error.WriteLine($"使用已保存凭证（捕获于 {profileExtCredentials.CapturedAt.ToLocalTime():yyyy-MM-dd HH:mm:ss}）。");
							if (credentials2.IsLikelyExpired(ProfileExtCredentials.KeyFreshnessThreshold))
							{
								Console.Error.WriteLine("提示：该凭证可能已过期（有效期约 30 分钟）；如请求失败请重新执行 official harvest。");
							}
						}
						else
						{
							if (text26 == null || text27 == null)
							{
								throw new ArgumentException("--key 与 --uin 必须同时提供（或都不提供以使用已保存凭证）。");
							}
							credentials2 = new ProfileExtCredentials(biz5, text27, text26, passTicket, DateTimeOffset.UtcNow);
						}
						OfficialAccountDateRange range = ParseArticleDateRange(args);
						string text28 = ReadOption(args, "--max-pages");
						int profileExtInterRequestDelayMilliseconds = options.ProfileExtInterRequestDelayMilliseconds;
						int profileExtPagesPerPause = options.ProfileExtPagesPerPause;
						int profileExtPauseMilliseconds = options.ProfileExtPauseMilliseconds;
						int maximumPages;
						if (text28 != null)
						{
							if (!int.TryParse(text28, out var result21) || result21 < 1 || result21 > 5000)
							{
								throw new ArgumentException("--max-pages 必须在 1 到 5000 之间。");
							}
							maximumPages = result21;
						}
						else
						{
							maximumPages = options.ProfileExtMaximumPages;
						}
						ProfileExtThrottleOptions throttle = new ProfileExtThrottleOptions(profileExtInterRequestDelayMilliseconds, profileExtPagesPerPause, profileExtPauseMilliseconds, maximumPages);
						string databasePath15 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath15, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						Console.Error.WriteLine("公众号文章枚举：以提供的凭证调用 profile_ext 接口从新到旧翻页并落库；" + $"每 {throttle.PagesPerPause} 页暂停 {(double)throttle.PauseMilliseconds / 1000.0:0.#} 秒规避频控；按 Ctrl+C 可取消。");
						if ((object)range != null)
						{
							Console.Error.WriteLine($"日期范围：{range.Start:yyyy-MM-dd} 至 {range.End:yyyy-MM-dd}（双闭，本机时区）。");
						}
						else
						{
							Console.Error.WriteLine("无日期范围：从上次断点继续；上次已翻到底时整轮重翻以补全更早历史（不增量早停）。");
						}
						OfficialAccountEnumerationReport officialAccountEnumerationReport = await new OfficialAccountEnumerationService(store, new ProfileExtClient(), throttle).EnumerateAsync(credentials2, cancellation.Token, range, null, allowEarlyStop: false);
						Console.Error.WriteLine("覆盖范围仅为 profile_ext 返回内容；到达日期起点不证明主页文章已采全。可用 articles cache 补充微信已加载缓存。");
						if (WantsJson(args, invocation, "articles backfill"))
						{
							ProfileExtEnumerationSummary summary = officialAccountEnumerationReport.Summary;
							int result15 = officialAccountEnumerationReport.StartOffset;
							int inserted = officialAccountEnumerationReport.Inserted;
							int updated = officialAccountEnumerationReport.Updated;
							var dateRange = (((object)range == null) ? null : new
							{
								start = range.Start,
								end = range.End
							});
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								Summary = summary,
								StartOffset = result15,
								Inserted = inserted,
								Updated = updated,
								source = "ProfileExtGetmsg",
								coverage = "sourceOnly",
								fullHistoryProven = false,
								dateRange = dateRange,
								exitCode = officialAccountEnumerationReport.Summary.Outcome switch
								{
									ProfileExtEnumerationOutcome.RateLimited => 5, 
									ProfileExtEnumerationOutcome.CredentialRejected => 4, 
									ProfileExtEnumerationOutcome.NetworkError => 3, 
									ProfileExtEnumerationOutcome.ServerRejected => 3, 
									ProfileExtEnumerationOutcome.HistoryUnavailable => 3, 
									ProfileExtEnumerationOutcome.InvalidResponse => 6, 
									ProfileExtEnumerationOutcome.Cancelled => 130, 
									_ => 0, 
								}
							}, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"枚举结束：{officialAccountEnumerationReport.Summary.Outcome}，起始 offset={officialAccountEnumerationReport.StartOffset}，翻 {officialAccountEnumerationReport.Summary.PagesFetched} 页，交付 {officialAccountEnumerationReport.Summary.TotalArticles} 篇，落库新增 {officialAccountEnumerationReport.Inserted}、更新 {officialAccountEnumerationReport.Updated}。{officialAccountEnumerationReport.Summary.Detail}");
						}
						if (officialAccountEnumerationReport.Summary.Outcome == ProfileExtEnumerationOutcome.RateLimited)
						{
							Console.Error.WriteLine("提示：已触发频控（ret 200013），本轮已立即停止。请冷却较长时间（建议 10 分钟以上）并重新获取 key 后再试。");
						}
						else if (officialAccountEnumerationReport.Summary.Outcome == ProfileExtEnumerationOutcome.CredentialRejected)
						{
							Console.Error.WriteLine("提示：key 很可能已过期（有效期约 30 分钟）。请在微信内置浏览器重新打开任一文章并复制新 key。");
						}
						return officialAccountEnumerationReport.Summary.Outcome switch
						{
							ProfileExtEnumerationOutcome.RateLimited => 5, 
							ProfileExtEnumerationOutcome.CredentialRejected => 4, 
							ProfileExtEnumerationOutcome.NetworkError => 3, 
							ProfileExtEnumerationOutcome.ServerRejected => 3, 
							ProfileExtEnumerationOutcome.HistoryUnavailable => 3, 
							ProfileExtEnumerationOutcome.InvalidResponse => 6, 
							ProfileExtEnumerationOutcome.Cancelled => 130, 
							_ => 0, 
						};
					}
					case "articles list":
					{
						string outputPath = ReadOption(args, "--biz") ?? throw new ArgumentException("articles list 必须提供 --biz。");
						OfficialAccountDateRange range = ParseArticleDateRange(args);
						string format2 = ResolveOutputFormat(args, invocation, "table");
						string text13 = format2;
						if ((!(text13 == "table") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + format2 + "。可选：table、json。");
						}
						string databasePath6 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath6, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<OfficialAccountArticle> readOnlyList3 = (((object)range != null) ? (await store.ListOfficialAccountArticlesAsync(outputPath, range, cancellation.Token)) : (await store.ListOfficialAccountArticlesAsync(outputPath, cancellation.Token)));
						IReadOnlyList<OfficialAccountArticle> readOnlyList4 = readOnlyList3;
						if (format2 == "json")
						{
							Console.WriteLine(JsonSerializer.Serialize(readOnlyList4.Select(LocalRecordReader.ArticleWithId), CliJson.Options));
						}
						else
						{
							foreach (OfficialAccountArticle item2 in readOnlyList4)
							{
								Console.WriteLine(((!item2.PublishedAt.HasValue) ? "????-??-??" : item2.PublishedAt.Value.ToLocalTime().ToString("yyyy-MM-dd", CultureInfo.CurrentCulture)) + "  " + (item2.Title ?? "(无标题)"));
								Console.WriteLine("         " + (item2.CanonicalUrl?.AbsoluteUri ?? item2.ContentUrl ?? "(无链接)"));
							}
						}
						if (format2 != "json")
						{
							Console.WriteLine($"共 {readOnlyList4.Count} 篇（articles list 只读取本地库；需要新数据先执行 articles backfill）。");
						}
						return 0;
					}
					case "articles discover":
					{
						string format2 = ReadOption(args, "--name") ?? throw new ArgumentException("必须提供 --name。");
						string biz2 = ReadOption(args, "--biz") ?? throw new ArgumentException("必须提供 --biz。");
						OfficialAccountDateRange range = ParseArticleDateRange(args) ?? throw new ArgumentException("必须提供 --from 与 --to。");
						string outputPath = ReadOption(args, "--out") ?? throw new ArgumentException("必须提供 --out 网址清单路径。");
						string format3 = ResolveOutputFormat(args, invocation, "text");
						string text13 = format3;
						if ((!(text13 == "text") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("--format 必须为 text 或 json。");
						}
						string text24 = ReadOption(args, "--max-scrolls");
						int num9;
						if (text24 != null)
						{
							if (!int.TryParse(text24, out var result13) || result13 < 0 || result13 > 500)
							{
								throw new ArgumentException("--max-scrolls 必须在 0 到 500 之间。");
							}
							num9 = result13;
						}
						else
						{
							num9 = 30;
						}
						num5 = num9;
						string databasePath11 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath11, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<OfficialAccountArticle> first = await store.ListOfficialAccountArticlesAsync(biz2, cancellation.Token);
						ProfileHistoryCacheReadResult profileHistoryCacheReadResult = ProfileHistoryCacheReader.Read(ProfileHistoryCacheReader.DefaultProfilesRoot(), new ProfileHistoryCacheReadOptions(biz2, null, 400, 67108864L, 268435456L));
						OfficialAccountArticle[] known = (from a in first.Concat(profileHistoryCacheReadResult.Articles).Concat(profileHistoryCacheReadResult.UrlOnlyArticles)
							group a by a.ArticleKey into g
							select g.First()).ToArray();
						using WeChatProfilePageAutomation page = new WeChatProfilePageAutomation();
						Console.Error.WriteLine("网址发现：核对主页文章清单；正文下载是独立阶段，缺失或歧义会保留在清单中。");
						ArticleLinkManifest articleLinkManifest = await new ArticleLinkDiscoveryService(page).DiscoverAsync(format2, biz2, range, known, outputPath, cancellation.Token, num5, null, null, delegate
						{
							ProfileHistoryCacheReadResult profileHistoryCacheReadResult2 = ProfileHistoryCacheReader.Read(ProfileHistoryCacheReader.DefaultProfilesRoot(), new ProfileHistoryCacheReadOptions(biz2, null, 400, 67108864L, 268435456L));
							return profileHistoryCacheReadResult2.Articles.Concat(profileHistoryCacheReadResult2.UrlOnlyArticles).ToArray();
						});
						if (format3 == "json")
						{
							Console.WriteLine(JsonSerializer.Serialize(articleLinkManifest, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"主页范围条目 {articleLinkManifest.ObservedCards}，网址已匹配 {articleLinkManifest.Articles.Count}，缺口 {articleLinkManifest.Gaps.Count}；清单：{outputPath}。终态：{articleLinkManifest.StopReason}。仅对已观察主页条目负责，不证明账号全量。");
						}
						return (!articleLinkManifest.LinksCompleteForObservedCards || !articleLinkManifest.RangeBoundaryObserved) ? 6 : 0;
					}
					case "articles cache":
					{
						string format3 = ReadOption(args, "--biz");
						ArgumentException.ThrowIfNullOrWhiteSpace(format3, "biz");
						OfficialAccountDateRange range = ParseArticleDateRange(args);
						string outputPath = ResolveOutputFormat(args, invocation, "text");
						string text13 = outputPath;
						if ((!(text13 == "text") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("--format 必须为 text 或 json。");
						}
						string databasePath10 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath10, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						OfficialAccountCacheImportReport officialAccountCacheImportReport = await new OfficialAccountProfileHistoryService(store).ImportLoadedAsync(format3, range, cancellation.Token);
						if (outputPath == "json")
						{
							Console.WriteLine(JsonSerializer.Serialize(officialAccountCacheImportReport, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"缓存匹配 {officialAccountCacheImportReport.Articles.Count} 篇，新增 {officialAccountCacheImportReport.Inserted}、更新 {officialAccountCacheImportReport.Updated}。");
							Console.WriteLine("只覆盖主页已加载缓存，不证明范围完整；缺少文章时请在微信主页加载目标日期后重试。");
						}
						return (officialAccountCacheImportReport.Articles.Count == 0) ? 3 : 0;
					}
					case "articles profile":
					{
						string outputPath = ReadOption(args, "--name");
						string biz4 = ReadOption(args, "--biz");
						if (string.IsNullOrWhiteSpace(outputPath) && string.IsNullOrWhiteSpace(biz4))
						{
							throw new ArgumentException("articles profile 必须提供 --name 公众号名称或 --biz 账号标识。");
						}
						num5 = ((int.TryParse(ReadOption(args, "--max-scrolls"), out var result19) && result19 >= 1 && result19 <= 500) ? result19 : 200);
						int result20;
						int count = ((int.TryParse(ReadOption(args, "--max-seconds"), out result20) && result20 >= 60 && result20 <= 3600) ? result20 : 900);
						string format3 = ResolveOutputFormat(args, invocation, "text");
						string text13 = format3;
						if ((!(text13 == "text") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + format3 + "。可选：text、json。");
						}
						OfficialAccountDateRange range = ParseArticleDateRange(args);
						if ((object)range != null)
						{
							Console.Error.WriteLine($"日期范围：{range.Start:yyyy-MM-dd} 至 {range.End:yyyy-MM-dd}（双闭，本机时区）；滚动到早于起点即停，入库仅限范围内。");
						}
						string databasePath14 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath14, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						if (string.IsNullOrWhiteSpace(outputPath))
						{
							outputPath = (await store.ListOfficialAccountsAsync(cancellation.Token)).FirstOrDefault((OfficialAccountCatalogAccount account) => string.Equals(account.Biz, biz4, StringComparison.Ordinal))?.DisplayName ?? throw new ArgumentException("本地账号目录中没有该 __biz 对应的显示名；请改用 --name 提供公众号名称。");
						}
						OfficialAccountProfileHistoryService officialAccountProfileHistoryService = new OfficialAccountProfileHistoryService(store);
						IProgress<OfficialAccountProfileHistoryProgress> progress4 = new Progress<OfficialAccountProfileHistoryProgress>(delegate(OfficialAccountProfileHistoryProgress officialAccountProfileHistoryProgress)
						{
							if (officialAccountProfileHistoryProgress.Phase == "scrolling")
							{
								Console.Error.WriteLine($"滚动中：有效 {officialAccountProfileHistoryProgress.ProductiveScrolls}/{officialAccountProfileHistoryProgress.AttemptedScrolls} 次，用时 {officialAccountProfileHistoryProgress.ElapsedSeconds:0} 秒（上限 {officialAccountProfileHistoryProgress.MaxScrolls} 次 / {officialAccountProfileHistoryProgress.MaxSeconds / 60} 分钟）。");
							}
							else if (officialAccountProfileHistoryProgress.Phase == "opened")
							{
								Console.Error.WriteLine("已进入主页，开始滚动加载…");
							}
						});
						string accountName = outputPath;
						CancellationToken token = cancellation.Token;
						string expectedBiz = biz4;
						int result18 = num5;
						double maxSeconds = count;
						OfficialAccountProfileHistoryReport officialAccountProfileHistoryReport = await officialAccountProfileHistoryService.CollectAsync(accountName, token, expectedBiz, new ProfilePageScrollOptions(null, null, null, null, result18, maxSeconds), progress4, range);
						if (format3 == "json")
						{
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								stopReason = officialAccountProfileHistoryReport.Scroll.StopReason.ToString(),
								attemptedScrolls = officialAccountProfileHistoryReport.Scroll.AttemptedScrolls,
								productiveScrolls = officialAccountProfileHistoryReport.Scroll.ProductiveScrolls,
								lastMarker = officialAccountProfileHistoryReport.Scroll.LastMarker,
								elapsedSeconds = officialAccountProfileHistoryReport.Scroll.ElapsedSeconds,
								decodedBlobs = officialAccountProfileHistoryReport.Cache.DecodedBlobs,
								skippedBlobs = officialAccountProfileHistoryReport.Cache.SkippedBlobs,
								entriesWithoutContent = officialAccountProfileHistoryReport.Cache.EntriesWithoutContent,
								rejectedEntries = officialAccountProfileHistoryReport.Cache.RejectedEntries,
								articles = officialAccountProfileHistoryReport.Cache.Articles.Count,
								inserted = officialAccountProfileHistoryReport.Inserted,
								updated = officialAccountProfileHistoryReport.Updated,
								biz = officialAccountProfileHistoryReport.Biz,
								accountName = officialAccountProfileHistoryReport.AccountName,
								fullHistoryProven = officialAccountProfileHistoryReport.FullHistoryProven
							}, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"滚动终态：{officialAccountProfileHistoryReport.Scroll.StopReason}（{officialAccountProfileHistoryReport.Scroll.ProductiveScrolls}/{officialAccountProfileHistoryReport.Scroll.AttemptedScrolls} 次有效/尝试，{officialAccountProfileHistoryReport.Scroll.ElapsedSeconds} 秒）。");
							Console.WriteLine($"缓存文章 {officialAccountProfileHistoryReport.Cache.Articles.Count} 篇，新入库 {officialAccountProfileHistoryReport.Inserted} 篇，更新 {officialAccountProfileHistoryReport.Updated} 篇。");
							Console.WriteLine("覆盖范围以主页缓存为准（已加载过的文章），不代表账号完整历史。");
						}
						return officialAccountProfileHistoryReport.Scroll.StopReason switch
						{
							ProfilePageScrollStopReason.OpenFailed => 3, 
							ProfilePageScrollStopReason.DocumentDisappeared => 0, 
							ProfilePageScrollStopReason.ScrollFailed => 3, 
							_ => 0, 
						};
					}
					case "articles link-refresh":
					{
						string name = ReadOption(args, "--name");
						string biz3 = ReadOption(args, "--biz");
						if (string.IsNullOrWhiteSpace(name) && string.IsNullOrWhiteSpace(biz3))
						{
							throw new ArgumentException("articles link-refresh 必须提供 --name 公众号名称或 --biz 账号标识。");
						}
						int result16;
						int count = ((int.TryParse(ReadOption(args, "--max-scrolls"), out result16) && result16 >= 1 && result16 <= 500) ? result16 : 60);
						num5 = ((int.TryParse(ReadOption(args, "--max-seconds"), out var result17) && result17 >= 60 && result17 <= 3600) ? result17 : 900);
						string format3 = ResolveOutputFormat(args, invocation, "text");
						string text13 = format3;
						if ((!(text13 == "text") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + format3 + "。可选：text、json。");
						}
						string databasePath13 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath13, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<OfficialAccountCatalogAccount> source2 = await store.ListOfficialAccountsAsync(cancellation.Token);
						if (string.IsNullOrWhiteSpace(name))
						{
							name = source2.FirstOrDefault((OfficialAccountCatalogAccount account) => string.Equals(account.Biz, biz3, StringComparison.Ordinal))?.DisplayName ?? throw new ArgumentException("本地账号目录中没有该 __biz 对应的显示名；请改用 --name 提供公众号名称。");
						}
						if (biz3 == null)
						{
							biz3 = source2.FirstOrDefault((OfficialAccountCatalogAccount account) => string.Equals(account.DisplayName, name, StringComparison.Ordinal))?.Biz ?? throw new ArgumentException("本地账号目录中没有该名称对应的 __biz；请先连接该公众号或提供 --biz。");
						}
						Console.Error.WriteLine("补链开始：在微信打开该号的一篇文章或主页，保持窗口可见；进度见下。");
						IProgress<OfficialAccountLinkRefreshProgress> progress3 = new Progress<OfficialAccountLinkRefreshProgress>(delegate(OfficialAccountLinkRefreshProgress officialAccountLinkRefreshProgress)
						{
							string phase = officialAccountLinkRefreshProgress.Phase;
							if ((phase == "capturing" || phase == "captured") ? true : false)
							{
								Console.Error.WriteLine($"已换得 {officialAccountLinkRefreshProgress.Captured}/{officialAccountLinkRefreshProgress.TotalTargets} 篇有效链接，用时 {officialAccountLinkRefreshProgress.ElapsedSeconds:0} 秒。");
							}
							else if (officialAccountLinkRefreshProgress.Phase == "scrolling")
							{
								Console.Error.WriteLine($"滚动加载更多卡片（已见 {officialAccountLinkRefreshProgress.CardsSeen} 张），用时 {officialAccountLinkRefreshProgress.ElapsedSeconds:0} 秒。");
							}
						});
						using WeChatProfilePageAutomation page = new WeChatProfilePageAutomation();
						OfficialAccountLinkRefreshReport officialAccountLinkRefreshReport = await new OfficialAccountLinkRefreshService(store).RefreshAsync(page, page, name, biz3, cancellation.Token, count, num5, progress3);
						if (format3 == "json")
						{
							Console.WriteLine(JsonSerializer.Serialize(officialAccountLinkRefreshReport, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"补链终态：{officialAccountLinkRefreshReport.StopReason}；换得有效链接 {officialAccountLinkRefreshReport.Captured}/{officialAccountLinkRefreshReport.Targets} 篇（卡片 {officialAccountLinkRefreshReport.CardsSeen} 张，{officialAccountLinkRefreshReport.ElapsedSeconds:0} 秒）。");
							if (officialAccountLinkRefreshReport.StopReason == "OpenFailed")
							{
								Console.Error.WriteLine("当前微信可见文档：" + string.Join("、", page.DescribeOpenDocuments()));
							}
							text13 = officialAccountLinkRefreshReport.StopReason;
							if ((!(text13 == "Completed") && !(text13 == "NoTargets")) || 1 == 0)
							{
								Console.WriteLine("未完成部分可稍后重跑；已换得的链接即时生效，可直接保存正文。");
							}
						}
						int result18;
						switch (officialAccountLinkRefreshReport.StopReason)
						{
						case "Completed":
						case "NoTargets":
							result18 = 0;
							break;
						case "OpenFailed":
						case "DocumentDisappeared":
						case "ScrollFailed":
							result18 = 3;
							break;
						default:
							result18 = 6;
							break;
						}
						return result18;
					}
					case "official harvest":
					{
						string format3 = ReadOption(args, "--article") ?? throw new ArgumentException("official harvest 必须提供 --article（该公众号任一篇文章链接，短链或长链均可）。");
						num5 = ((int.TryParse(ReadOption(args, "--timeout-seconds"), out var result6) && result6 >= 10 && result6 <= 900) ? result6 : 180);
						using HttpClient http = new HttpClient();
						ResolvedOfficialArticle resolved = await OfficialAccountArticleLinkResolver.TryResolveAsync(http, format3, cancellation.Token, identityOnly: true);
						RuntimeEventSource.Emit(AppLogLevel.Information, "OFFICIAL_ACCOUNT_ARTICLE_RESOLVED", "Program", "文章链接公开解析完成。", new Dictionary<string, object>
						{
							["resolved"] = (object)resolved != null,
							["account"] = (((object)resolved == null) ? null : OfficialAccountLogTags.AccountTag(resolved.Biz)),
							["hasNickname"] = resolved?.Nickname != null,
							["hasTitle"] = resolved?.Title != null,
							["hasAppMsgId"] = (resolved?.AppMsgId).HasValue,
							["usedUrlBizFallback"] = false
						});
						string outputPath;
						if ((object)resolved != null)
						{
							outputPath = resolved.Biz;
							Console.WriteLine($"文章归属：{resolved.Nickname ?? "(未知公众号)"}（__biz={resolved.Biz}）");
							if (resolved.Title != null)
							{
								Console.WriteLine("示例文章：" + resolved.Title);
							}
							if (resolved.PublishedAt.HasValue)
							{
								Console.WriteLine($"发布时间：{resolved.PublishedAt.Value.ToLocalTime():yyyy-MM-dd HH:mm}");
							}
						}
						else
						{
							if (!OfficialAccountArticleLinkResolver.TryExtractBizFromUrl(format3, out string biz))
							{
								throw new ArgumentException("无法从该链接解析出公众号：请确认是 mp.weixin.qq.com 的文章链接。");
							}
							outputPath = biz;
							Console.WriteLine("公开页解析失败，已从链接参数取得 __biz=" + outputPath + "。");
							RuntimeEventSource.Emit(AppLogLevel.Information, "OFFICIAL_ACCOUNT_ARTICLE_RESOLVED", "Program", "公开页解析失败，已回退到链接 __biz 参数。", new Dictionary<string, object>
							{
								["resolved"] = true,
								["account"] = OfficialAccountLogTags.AccountTag(outputPath),
								["hasNickname"] = false,
								["hasTitle"] = false,
								["hasAppMsgId"] = false,
								["usedUrlBizFallback"] = true
							});
						}
						Console.WriteLine($"请在微信中打开该公众号的任意一篇文章（{num5} 秒内）。" + "程序只读浏览器窗口地址，不点击、不输入、不移动鼠标。");
						using (OfficialAccountCredentialWatcher watcher = new OfficialAccountCredentialWatcher())
						{
							ProfileExtCredentials credentials = await watcher.WaitForCredentialsAsync(TimeSpan.FromSeconds(num5), cancellation.Token, outputPath);
							if ((object)credentials == null)
							{
								RuntimeEventSource.Emit(AppLogLevel.Warning, "OFFICIAL_ACCOUNT_CREDENTIAL_WATCH_TIMED_OUT", "Program", "等待用户打开文章超时，未捕获到凭证。", new Dictionary<string, object>
								{
									["timeoutSeconds"] = num5,
									["account"] = OfficialAccountLogTags.AccountTag(outputPath)
								});
								if (WantsJson(args, invocation, "official harvest"))
								{
									Console.WriteLine(JsonSerializer.Serialize(new
									{
										captured = false,
										timeoutSeconds = num5,
										biz = outputPath,
										credentialSaved = false
									}, CliJson.Options));
								}
								else
								{
									Console.WriteLine("超时未捕获到凭证。请确认已在微信内置浏览器（而非系统浏览器）打开文章后重试；key 有效期约 30 分钟，捕获后请尽快执行 articles backfill。");
								}
								return 4;
							}
							if (!string.Equals(credentials.Biz, outputPath, StringComparison.Ordinal))
							{
								Console.WriteLine($"提示：捕获到的文章属于 __biz={credentials.Biz}，与目标 {outputPath} 不同。" + "key 未必跨公众号通用，建议打开目标公众号自己的文章。");
							}
							new ProfileExtCredentialStore().Save(credentials);
							RuntimeEventSource.Emit(AppLogLevel.Information, "OFFICIAL_ACCOUNT_CREDENTIAL_HARVESTED", "Program", "已捕获 getmsg 凭证并以 DPAPI 加密保存。", new Dictionary<string, object>
							{
								["bizLength"] = credentials.Biz.Length,
								["hasPassTicket"] = credentials.PassTicket != null
							});
							string databasePath5 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
							SqliteMessageStore store = new SqliteMessageStore(databasePath5, options.BackupRetentionCount);
							await store.InitializeAsync(cancellation.Token);
							bool flag2 = resolved?.Nickname == null;
							if (flag2)
							{
								flag2 = !(await store.ListOfficialAccountsAsync(cancellation.Token)).Any((OfficialAccountCatalogAccount account) => account.Biz == credentials.Biz && account.IdentityStatus == OfficialAccountIdentityStatus.Resolved);
							}
							if (flag2)
							{
								Console.Error.WriteLine("凭据已保存，正在补充公众号名称…");
								ResolvedOfficialArticle resolvedOfficialArticle = await OfficialAccountArticleLinkResolver.TryResolveAsync(http, format3, cancellation.Token);
								if (resolvedOfficialArticle?.Biz == credentials.Biz)
								{
									resolved = resolvedOfficialArticle;
								}
							}
							OfficialAccountDirectoryService.OfficialAccountCatalogUpgrade officialAccountCatalogUpgrade = await new OfficialAccountDirectoryService(store).UpgradeFromArticleAsync(resolved, credentials.Biz, cancellation.Token);
							if ((object)officialAccountCatalogUpgrade != null && officialAccountCatalogUpgrade.Resolution == OfficialAccountIdentityResolution.Conflict)
							{
								Console.WriteLine("提示：该公众号 ID 已绑定到其他名称候选，目录保持待确认，未自动合并。");
							}
							else if ((object)officialAccountCatalogUpgrade != null)
							{
								Console.WriteLine("账号目录：" + (resolved?.Nickname ?? "已连接公众号（名称待补充）") + " 已记录并绑定 __biz（来源：文章链接）。");
							}
							if (WantsJson(args, invocation, "official harvest"))
							{
								Console.WriteLine(JsonSerializer.Serialize(new
								{
									captured = true,
									resolved = ((object)resolved != null),
									nickname = resolved?.Nickname,
									title = resolved?.Title,
									publishedAt = resolved?.PublishedAt,
									biz = credentials.Biz,
									credentialCapturedAt = credentials.CapturedAt,
									credentialSaved = true,
									identityConflict = ((object)officialAccountCatalogUpgrade != null && officialAccountCatalogUpgrade.Resolution == OfficialAccountIdentityResolution.Conflict),
									nextCommand = "articles backfill --biz " + credentials.Biz
								}, CliJson.Options));
							}
							else
							{
								Console.WriteLine($"凭证已捕获并加密保存（__biz={credentials.Biz}）。下一步执行：articles backfill --biz {credentials.Biz} [--from 日期 --to 日期]");
							}
						}
						return 0;
					}
					case "articles body":
					{
						string outputPath = ReadOption(args, "--biz") ?? throw new ArgumentException("articles body 必须提供 --biz（建议先执行 articles discover 获取网址清单）。");
						string format3 = ReadOption(args, "--out");
						OfficialAccountDateRange range = ParseArticleDateRange(args);
						string format2 = ReadOption(args, "--manifest");
						ArticleLinkManifest linkManifest = null;
						IReadOnlyList<OfficialAccountArticle> manifestArticles = null;
						if (format2 != null)
						{
							if ((object)range != null || ReadOption(args, "--limit") != null)
							{
								throw new ArgumentException("--manifest 固定下载范围，不能与 --from/--to/--limit 同用。");
							}
							linkManifest = ArticleLinkManifest.Read(format2);
							manifestArticles = linkManifest.DownloadArticles(outputPath);
						}
						string text18 = ReadOption(args, "--limit");
						int? obj2;
						if (text18 != null)
						{
							if (!int.TryParse(text18, out var result8) || result8 < 1 || result8 > 5000)
							{
								throw new ArgumentException("--limit 必须在 1 到 5000 之间。");
							}
							obj2 = result8;
						}
						else
						{
							obj2 = null;
						}
						int? limit = obj2;
						string text19 = ReadOption(args, "--delay-ms");
						int num7;
						if (text19 != null)
						{
							if (!int.TryParse(text19, out var result9) || result9 < 0 || result9 > 600000)
							{
								throw new ArgumentException("--delay-ms 必须在 0 到 600000 之间。");
							}
							num7 = result9;
						}
						else
						{
							num7 = ArticleBodyHarvestOptions.Default.InterArticleDelayMilliseconds;
						}
						num5 = num7;
						string text20 = ReadOption(args, "--retry");
						int num8;
						if (text20 != null)
						{
							if (!int.TryParse(text20, out var result10) || result10 < 1 || result10 > 10)
							{
								throw new ArgumentException("--retry 必须在 1 到 10 之间。");
							}
							num8 = result10;
						}
						else
						{
							num8 = 3;
						}
						int count = num8;
						bool onlyFailed = ReadOption(args, "--only-failed") != null;
						string databasePath7 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath7, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						if (manifestArticles != null)
						{
							await store.UpsertOfficialAccountArticlesAsync(manifestArticles, cancellation.Token);
						}
						string outputRoot = format3 ?? Path.Combine(Path.GetDirectoryName(databasePath7) ?? Environment.CurrentDirectory, "article-bodies");
						ProtectedFileSystem.CreateDirectory(outputRoot);
						bool flag3 = CliOptionReader.IsPresent(args, "--from-cache");
						if (manifestArticles != null)
						{
							Console.Error.WriteLine($"固定网址清单：{manifestArticles.Count} 篇，按清单身份重试，不扩展到库内其他文章。");
						}
						Console.Error.WriteLine((flag3 ? "正文采集：读取本地正文快照，图片仍需联网，" : "正文采集：按库内 content_url（含 chksm）抓取文章页，") + "转 Markdown 输出到 " + outputRoot + "。" + $"篇间隔 {(double)num5 / 1000.0:0.#} 秒；已完成文章自动跳过{(onlyFailed ? "，本轮仅重试上次失败篇" : string.Empty)}，可随时 Ctrl+C 中断续跑。");
						if ((object)range != null)
						{
							Console.Error.WriteLine($"日期范围：{range.Start:yyyy-MM-dd} 至 {range.End:yyyy-MM-dd}（双闭，本机时区）。");
						}
						ArticleBodyHarvestOptions harvestOptions = new ArticleBodyHarvestOptions(limit, num5, count, onlyFailed, flag3);
						ArticleBodyHarvestReport articleBodyHarvestReport = await new ArticleBodyHarvestService(store, new ArticleBodyFetcher(null, count), new ArticleBodyAssetDownloader(), harvestOptions).HarvestAsync(progress: new Progress<ArticleBodyHarvestProgress>(delegate(ArticleBodyHarvestProgress p)
						{
							Console.Error.WriteLine($"  进度 {p.Processed}/{p.Total}：成功 {p.Succeeded}，失败 {p.Failed}");
						}), biz: outputPath, outputDirectory: outputRoot, cancellationToken: cancellation.Token, range: range, sourceArticles: manifestArticles);
						if (WantsJson(args, invocation, "articles body"))
						{
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								Total = articleBodyHarvestReport.Total,
								Succeeded = articleBodyHarvestReport.Succeeded,
								Failed = articleBodyHarvestReport.Failed,
								SkippedAlreadyDone = articleBodyHarvestReport.SkippedAlreadyDone,
								CancelledPending = articleBodyHarvestReport.CancelledPending,
								outputDirectory = outputRoot,
								dateRange = (((object)range == null) ? null : new
								{
									start = range.Start,
									end = range.End
								}),
								onlyFailed = onlyFailed,
								manifestDateRange = (((object)linkManifest == null) ? null : new
								{
									start = linkManifest.From,
									end = linkManifest.To
								}),
								manifest = format2,
								manifestArticleCount = manifestArticles?.Count,
								bodySource = (harvestOptions.FromCache ? "localCacheSnapshot" : "network")
							}, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"正文采集结束：待抓 {articleBodyHarvestReport.Total} 篇，成功 {articleBodyHarvestReport.Succeeded}，失败 {articleBodyHarvestReport.Failed}，跳过（已完成）{articleBodyHarvestReport.SkippedAlreadyDone}" + ((articleBodyHarvestReport.CancelledPending > 0) ? $"，取消时未处理 {articleBodyHarvestReport.CancelledPending} 篇（下轮自动续采）" : string.Empty) + "。失败的篇目可重跑 articles body 重试（URL 与 chksm 可重复使用）。");
						}
						return (cancellation.IsCancellationRequested || articleBodyHarvestReport.CancelledPending > 0) ? 130 : ((articleBodyHarvestReport.Failed > 0) ? 6 : 0);
					}
					case "official search":
					{
						string accountName2 = ReadOption(args, "--name") ?? throw new ArgumentException("official search 必须提供 --name（公众号名称，尽量完整）。");
						string outputRoot = ReadOption(args, "--account-id");
						Console.Error.WriteLine("正在连接微信：搜索公众号并打开文章读取凭据，请暂时不要操作微信窗口。");
						RuntimeEventSource.Emit(AppLogLevel.Information, "OFFICIAL_ACCOUNT_CLIENT_SEARCH_STARTED", "Program", "CLI 触发客户端检索导航。", new Dictionary<string, object> { ["fromDirectoryRow"] = outputRoot != null });
						using OfficialAccountClientSearchNavigator navigator = new OfficialAccountClientSearchNavigator();
						OfficialAccountClientSearchOutcome outcome = await navigator.SearchAsync(accountName2, cancellation.Token, delegate(string stage)
						{
							Console.Error.WriteLine("· " + stage);
						});
						if (!outcome.IsSuccess)
						{
							RuntimeEventSource.Emit(AppLogLevel.Warning, "OFFICIAL_ACCOUNT_CLIENT_SEARCH_FAILED", "Program", "客户端检索导航未完成。", new Dictionary<string, object> { ["status"] = outcome.Status.ToString() });
							Console.WriteLine($"未完成（{outcome.Status}）：{outcome.FailureDetail}");
							return outcome.Status switch
							{
								OfficialAccountClientSearchStatus.AmbiguousMatch => 2, 
								OfficialAccountClientSearchStatus.Cancelled => 130, 
								OfficialAccountClientSearchStatus.CredentialsNotCaptured => 4, 
								_ => 3, 
							};
						}
						OfficialAccountClientSearchResult result22 = outcome.Result;
						new ProfileExtCredentialStore().Save(result22.Credentials);
						string databasePath16 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath16, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						OfficialAccountDirectoryService.OfficialAccountCatalogUpgrade officialAccountCatalogUpgrade2 = await new OfficialAccountDirectoryService(store).UpgradeFromClientSearchAsync(result22.DisplayName, result22.Credentials.Biz, outputRoot, cancellation.Token);
						if (officialAccountCatalogUpgrade2.Resolution == OfficialAccountIdentityResolution.Conflict)
						{
							Console.WriteLine("提示：该公众号 ID 已绑定到其他名称候选，目录保持待确认，未自动合并。");
						}
						if (WantsJson(args, invocation, "official search"))
						{
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								status = outcome.Status.ToString(),
								success = true,
								failureDetail = (string)null,
								displayName = result22.DisplayName,
								biz = result22.Credentials.Biz,
								credentialCapturedAt = result22.Credentials.CapturedAt,
								credentialSaved = true,
								identityResolution = officialAccountCatalogUpgrade2.Resolution.ToString(),
								nextCommand = "articles backfill --biz " + result22.Credentials.Biz
							}, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"已完成：{result22.DisplayName}（__biz={result22.Credentials.Biz}），凭证已加密保存。");
							Console.WriteLine("下一步执行：articles backfill --biz " + result22.Credentials.Biz + " [--from 日期 --to 日期]");
						}
						return 0;
					}
					case "db list-contacts":
					case "db list-messages":
					case "db message-stats":
					case "db contact-stats":
					case "db import-messages":
					case "db import-contacts":
					{
						string outputRoot = command switch
						{
							"db import-contacts" => "import-contacts", 
							"db import-messages" => "import-messages", 
							"db list-contacts" => "list", 
							"db list-messages" => "message-list", 
							"db contact-stats" => "stats", 
							_ => "message-stats", 
						};
						string databasePath9 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath9, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						string text21 = ResolveOutputFormat(args, invocation, "table");
						if ((!(text21 == "table") && !(text21 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + text21 + "。可选：table、json。");
						}
						bool onlyFailed = text21 == "json";
						if (string.Equals(outputRoot, "import-contacts", StringComparison.OrdinalIgnoreCase))
						{
							string accountRootPath = ReadOption(args, "--account-root");
							string wechatInstallDirectory = ReadOption(args, "--wechat-dir");
							WechatContactImportService wechatContactImportService = new WechatContactImportService(store, null, null, wechatInstallDirectory);
							Progress<string> progress = new Progress<string>(delegate(string value12)
							{
								Console.Error.WriteLine(value12);
							});
							WechatContactImportResult wechatContactImportResult = await wechatContactImportService.ImportAsync(accountRootPath, progress, cancellation.Token);
							if (!wechatContactImportResult.Success)
							{
								if (onlyFailed)
								{
									Console.WriteLine(JsonSerializer.Serialize(wechatContactImportResult, CliJson.Options));
								}
								else
								{
									Console.Error.WriteLine("导入失败：" + wechatContactImportResult.Error);
								}
								return 3;
							}
							if (onlyFailed)
							{
								Console.WriteLine(JsonSerializer.Serialize(wechatContactImportResult, CliJson.Options));
								return 0;
							}
							Console.WriteLine($"导入完成：好友 {wechatContactImportResult.FriendCount}、身份条目 {wechatContactImportResult.ContactCount}、群聊 {wechatContactImportResult.ChatRoomCount}、群成员 {wechatContactImportResult.MemberCount}（{(wechatContactImportResult.UsedCachedKey ? "缓存密钥" : "内存扫描提取")}，耗时 {wechatContactImportResult.ElapsedMilliseconds}ms）。");
							return 0;
						}
						if (string.Equals(outputRoot, "list", StringComparison.OrdinalIgnoreCase))
						{
							string databasePath7 = ReadOption(args, "--search");
							int result11;
							int value7 = (int.TryParse(ReadOption(args, "--limit"), out result11) ? result11 : 50);
							IReadOnlyList<WechatContactEntry> readOnlyList5 = await store.ListWechatContactsAsync(Math.Clamp(value7, 1, 1000), databasePath7, cancellation.Token);
							if (onlyFailed)
							{
								Console.WriteLine(JsonSerializer.Serialize(new
								{
									count = readOnlyList5.Count,
									search = databasePath7,
									contacts = readOnlyList5
								}, CliJson.Options));
								return 0;
							}
							if (readOnlyList5.Count == 0)
							{
								Console.WriteLine("联系人为空：先执行 db import-contacts 导入。");
								return 0;
							}
							foreach (WechatContactEntry item3 in readOnlyList5)
							{
								Console.WriteLine("  " + (item3.Remark ?? item3.NickName ?? item3.Username) + " | " + item3.Username + (string.IsNullOrEmpty(item3.Alias) ? string.Empty : (" | " + item3.Alias)) + (item3.IsChatRoom ? " | 群聊" : string.Empty));
							}
							return 0;
						}
						if (string.Equals(outputRoot, "import-messages", StringComparison.OrdinalIgnoreCase))
						{
							string accountRootPath2 = ReadOption(args, "--account-root");
							string wechatInstallDirectory2 = ReadOption(args, "--wechat-dir");
							WechatDbMessageImportResult wechatDbMessageImportResult = await new WechatMessageImportService(store, null, null, wechatInstallDirectory2).ImportAsync(progress: new Progress<string>(delegate(string value12)
							{
								Console.Error.WriteLine(value12);
							}), accountRootPath: accountRootPath2, filesRoot: string.IsNullOrWhiteSpace(options.AttachmentSourceDirectory) ? null : ConfigurationLoader.ResolvePath(options.AttachmentSourceDirectory, settingsDirectory), cancellationToken: cancellation.Token, full: args.Contains<string>("--full", StringComparer.OrdinalIgnoreCase));
							if (!wechatDbMessageImportResult.Success)
							{
								if (onlyFailed)
								{
									Console.WriteLine(JsonSerializer.Serialize(wechatDbMessageImportResult, CliJson.Options));
								}
								else
								{
									Console.Error.WriteLine($"同步未完成：{wechatDbMessageImportResult.Error} 已新增 {wechatDbMessageImportResult.InsertedCount}，更新 {wechatDbMessageImportResult.UpdatedCount}，失败库 {wechatDbMessageImportResult.FailedDatabaseCount}；已提交批次可续传。");
								}
								return 3;
							}
							if (onlyFailed)
							{
								Console.WriteLine(JsonSerializer.Serialize(wechatDbMessageImportResult, CliJson.Options));
								return 0;
							}
							Console.WriteLine($"消息导入完成：{wechatDbMessageImportResult.ConversationCount} 个会话、{wechatDbMessageImportResult.MessageCount} 条消息（新增 {wechatDbMessageImportResult.InsertedCount}、更新 {wechatDbMessageImportResult.UpdatedCount}、解析成功 {wechatDbMessageImportResult.ParsedCount}、部分解析 {wechatDbMessageImportResult.PartialCount}、失败 {wechatDbMessageImportResult.FailedCount}，{(wechatDbMessageImportResult.UsedCachedKey ? "缓存密钥" : "内存扫描提取")}，耗时 {wechatDbMessageImportResult.ElapsedMilliseconds}ms）。");
							return 0;
						}
						if (string.Equals(outputRoot, "message-stats", StringComparison.OrdinalIgnoreCase))
						{
							WechatDbMessageImportStats wechatDbMessageImportStats = await store.GetDbMessageImportStatsAsync(cancellation.Token);
							if (onlyFailed)
							{
								Console.WriteLine(JsonSerializer.Serialize(wechatDbMessageImportStats, CliJson.Options));
								return 0;
							}
							string obj3 = $"已导入消息 {wechatDbMessageImportStats.MessageCount} 条（解析成功 {wechatDbMessageImportStats.ParsedCount}），覆盖 {wechatDbMessageImportStats.ConversationCount} 个会话，";
							DateTimeOffset? lastImportFinishedAt = wechatDbMessageImportStats.LastImportFinishedAt;
							object obj4;
							if (lastImportFinishedAt.HasValue)
							{
								DateTimeOffset valueOrDefault2 = lastImportFinishedAt.GetValueOrDefault();
								obj4 = $"最近导入 {valueOrDefault2.ToLocalTime():yyyy-MM-dd HH:mm:ss}。";
							}
							else
							{
								obj4 = "尚未导入消息。";
							}
							Console.WriteLine(obj3 + (string?)obj4);
							return 0;
						}
						if (string.Equals(outputRoot, "message-list", StringComparison.OrdinalIgnoreCase))
						{
							string databasePath7 = ReadOption(args, "--account-root");
							IReadOnlyList<string> readOnlyList6 = await store.ListDbAccountsAsync(cancellation.Token);
							object obj5;
							if (databasePath7 == null)
							{
								if (readOnlyList6.Count > 1)
								{
									throw new ArgumentException("存在多个导入账号，请用 --account-root 指定账号目录。");
								}
								obj5 = readOnlyList6.FirstOrDefault() ?? "";
							}
							else
							{
								obj5 = OperatingSystem.IsMacOS()
									? Path.GetFileName(macImports.ResolveAccountRoot(databasePath7))
									: WechatMessageImportService.AccountKey(databasePath7);
							}
							string accountKey = (string)obj5;
							string format2 = ReadOption(args, "--conversation") ?? throw new ArgumentException("db list-messages 必须提供 --conversation（会话 username）。");
							int result12;
							int value8 = (int.TryParse(ReadOption(args, "--limit"), out result12) ? result12 : 20);
							string text22 = ReadOption(args, "--from");
							string text23 = ReadOption(args, "--to");
							DateTimeOffset? messageFrom = ((text22 == null) ? ((DateTimeOffset?)null) : new DateTimeOffset?(StartOfDayLocal(ParseDateOnly(text22, "--from"))));
							DateTimeOffset? messageTo = ((text23 == null) ? ((DateTimeOffset?)null) : new DateTimeOffset?(EndOfDayLocal(ParseDateOnly(text23, "--to"))));
							if (messageFrom.HasValue && messageTo.HasValue && messageFrom > messageTo)
							{
								throw new ArgumentException("--from 不能晚于 --to。");
							}
							IReadOnlyList<WechatDbMessage> readOnlyList7 = await store.ListDbMessagesAsync(format2, Math.Clamp(value8, 1, 500), messageFrom, messageTo, cancellation.Token, accountKey);
							if (onlyFailed)
							{
								bool includeRaw = CliOptionReader.IsPresent(args, "--include-raw");
								Console.WriteLine(JsonSerializer.Serialize(new
								{
									conversation = format2,
									from = messageFrom,
									to = messageTo,
									count = readOnlyList7.Count,
									includeRaw = includeRaw,
									messages = readOnlyList7.Select((WechatDbMessage wechatDbMessage) => new
									{
										ServerId = wechatDbMessage.ServerId,
										ServerSeq = wechatDbMessage.ServerSeq,
										LocalId = wechatDbMessage.LocalId,
										Type = wechatDbMessage.Type,
										TypeRaw = wechatDbMessage.TypeRaw,
										AppMsgSubType = wechatDbMessage.AppMsgSubType,
										ConversationUsername = wechatDbMessage.ConversationUsername,
										RealSenderId = wechatDbMessage.RealSenderId,
										SenderUsername = wechatDbMessage.SenderUsername,
										CreateTime = wechatDbMessage.CreateTime,
										ParseStatus = wechatDbMessage.ParseStatus,
										PlainContent = wechatDbMessage.PlainContent,
										ContentLength = wechatDbMessage.ContentLength,
										IsSelf = wechatDbMessage.IsSelf,
										HasKnownDirection = wechatDbMessage.HasKnownDirection,
										SourceSummary = wechatDbMessage.SourceSummary,
										RawContent = (includeRaw ? wechatDbMessage.RawContent : null)
									})
								}, CliJson.Options));
								return 0;
							}
							if (readOnlyList7.Count == 0)
							{
								Console.WriteLine("该会话没有已导入消息：先执行 db import-messages。");
								return 0;
							}
							foreach (WechatDbMessage item4 in readOnlyList7)
							{
								string value9 = ((item4.PlainContent == null) ? $"[{item4.Type}]" : ((item4.PlainContent.Length > 60) ? (item4.PlainContent.Substring(0, 60) + "…") : item4.PlainContent));
								Console.WriteLine($"  {item4.CreateTime.ToLocalTime():yyyy-MM-dd HH:mm} | " + (item4.SenderUsername ?? item4.RealSenderId.ToString()) + (item4.IsSelf ? "（我）" : "") + $" | {item4.ParseStatus} | {value9}");
							}
							return 0;
						}
						if (string.Equals(outputRoot, "stats", StringComparison.OrdinalIgnoreCase))
						{
							WechatContactDirectoryStats wechatContactDirectoryStats = await store.GetWechatContactDirectoryStatsAsync(cancellation.Token);
							if (onlyFailed)
							{
								Console.WriteLine(JsonSerializer.Serialize(wechatContactDirectoryStats, CliJson.Options));
								return 0;
							}
							string obj6 = $"身份条目 {wechatContactDirectoryStats.ContactCount}、群聊 {wechatContactDirectoryStats.ChatRoomCount}、群成员关系 {wechatContactDirectoryStats.MemberCount}，";
							DateTimeOffset? lastImportFinishedAt2 = wechatContactDirectoryStats.LastImportFinishedAt;
							object obj7;
							if (lastImportFinishedAt2.HasValue)
							{
								DateTimeOffset valueOrDefault3 = lastImportFinishedAt2.GetValueOrDefault();
								obj7 = $"最近导入 {valueOrDefault3.ToLocalTime():yyyy-MM-dd HH:mm:ss}。";
							}
							else
							{
								obj7 = "尚未导入。";
							}
							Console.WriteLine(obj6 + (string?)obj7);
							return 0;
						}
						Console.Error.WriteLine("该分支理论上不可达：未知的 db 动词已在解析层被拒绝。");
						return 2;
					}
					case "official list":
					{
						string databasePath3 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath3, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<OfficialAccountDirectoryEntry> readOnlyList2 = await new OfficialAccountDirectoryService(store).ReadAsync(cancellation.Token);
						bool flag = string.Equals(ResolveOutputFormat(args, invocation, "table"), "json", StringComparison.Ordinal);
						if (readOnlyList2.Count == 0 && !flag)
						{
							Console.WriteLine("账号目录为空：启动采集器可从聚合摘要积累名称候选，或用 official search 抓取身份。");
							return 0;
						}
						if (flag)
						{
							Console.WriteLine(JsonSerializer.Serialize(readOnlyList2.Select((OfficialAccountDirectoryEntry entry) => new
							{
								displayName = entry.DisplayName,
								biz = entry.Biz,
								identityStatus = entry.IdentityStatus.ToString(),
								states = new
								{
									observed = entry.States.Observed,
									resolved = entry.States.Resolved,
									harvestable = entry.States.Harvestable,
									resumable = entry.States.Resumable,
									credentialExpired = entry.States.CredentialExpired,
									searchable = entry.States.Searchable
								},
								articleCount = entry.ArticleCount,
								lastCursorOutcome = entry.LastCursorOutcome,
								hasAlbumSeed = entry.HasAlbumSeed,
								cursorUpdatedAt = entry.CursorUpdatedAt,
								credentialValidatedAt = entry.CredentialValidatedAt,
								credentialCapturedAt = entry.CredentialCapturedAt,
								discoverySource = entry.DiscoverySource,
								lastObservedAt = entry.LastObservedAt
							}), CliJson.Options));
							return 0;
						}
						Console.WriteLine($"共 {readOnlyList2.Count} 个账号（目录不代表完整关注列表）：");
						foreach (OfficialAccountDirectoryEntry item5 in readOnlyList2)
						{
							string value3 = item5.IdentityStatus switch
							{
								OfficialAccountIdentityStatus.Resolved => "已解析", 
								OfficialAccountIdentityStatus.Conflict => "冲突待确认", 
								_ => "仅发现", 
							};
							string value4 = ((item5.Biz == null) ? "—" : ((!item5.CredentialCapturedAt.HasValue) ? "无凭证" : (item5.States.CredentialExpired ? "已过期" : "新鲜")));
							string discoverySource = item5.DiscoverySource;
							string value5 = discoverySource switch
							{
								"AggregatorSummary" => "微信摘要", 
								"ArticleLink" => "文章链接", 
								"ClientSearch" => "客户端检索", 
								_ => discoverySource, 
							};
							Console.WriteLine($"  {item5.DisplayName} | {value3} | {value4} | 文章 {item5.ArticleCount} | 游标 {item5.LastCursorOutcome ?? "—"} | {value5}" + ((item5.Biz == null) ? string.Empty : (" | __biz=" + item5.Biz)));
						}
						return 0;
					}
					case "debug browser-windows":
					{
						using OfficialAccountCredentialWatcher officialAccountCredentialWatcher = new OfficialAccountCredentialWatcher();
						Console.WriteLine(JsonSerializer.Serialize(officialAccountCredentialWatcher.ProbeBrowserWindows(cancellation.Token), CliJson.Options));
						return 0;
					}
					case "debug image-decode":
					{
						string text35 = ReadOption(args, "--dat") ?? throw new ArgumentException("debug image-decode 必须提供 --dat 微信图片缓存文件。");
						string outputRoot = ReadOption(args, "--output") ?? throw new ArgumentException("debug image-decode 必须提供 --output 输出文件路径（扩展名会自动校正）。");
						string format2 = ConfigurationLoader.ResolvePath(text35);
						string path7 = ConfigurationLoader.ResolvePath(ReadOption(args, "--template") ?? text35);
						if (OperatingSystem.IsMacOS() && WechatLocalImportProviders.Current is IWechatLocalMediaProvider localMedia)
						{
							WechatImagePreviewResult image;
							try { image = await localMedia.DecodeAccountImageAsync(format2, path7, cancellation.Token); }
							catch (IOException) { throw new CliEnvironmentException("图片诊断未完成；账号来源、图片或缓存密钥未通过校验。"); }
							if (!image.Success || image.Bytes is null) throw new CliEnvironmentException("图片诊断未完成，未写入输出。");
							var target = localMedia.ProtectMediaOutput(Path.ChangeExtension(ConfigurationLoader.ResolvePath(outputRoot), image.Extension), ResolveDatabasePath(databaseOverride, options, settingsDirectory));
							if (File.Exists(target) || Directory.Exists(target)) throw new ArgumentException("输出路径已存在，请选择新文件。");
							ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(target)!);
							var temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
							try { await ProtectedFileSystem.WriteAllBytesAsync(temporary, image.Bytes, cancellation.Token); cancellation.Token.ThrowIfCancellationRequested(); ProtectedFileSystem.Move(temporary, target); }
							finally { if (File.Exists(temporary)) ProtectedFileSystem.Delete(temporary); }
							bool cached = image.KeySource == WechatImageKeySource.ProtectedCache;
							appLogger.Log(AppLogLevel.Information, "WECHAT_IMAGE_PROBE_SUCCEEDED", "Program", "本机图片已通过账号内只读解码验证。", new Dictionary<string, object> { ["format"] = image.MediaType!, ["byteSize"] = image.Bytes.Length, ["keyCacheUsed"] = cached, ["keySource"] = image.KeySource.ToString() });
							if (WantsJson(args, invocation, "debug image-decode")) Console.WriteLine(JsonSerializer.Serialize(new { path = target, format = image.MediaType, byteSize = image.Bytes.Length, keyCacheUsed = cached, keySource = image.KeySource.ToString(), processId = (int?)null }, CliJson.Options));
							else Console.WriteLine($"验证成功：{image.MediaType}，{image.Bytes.Length} 字节，已写入 {target}");
							return 0;
						}
						WechatImageTemplate template = WechatImageV2Decoder.ReadTemplate(path7);
						Progress<WechatImageKeyScanProgress> progress5 = new Progress<WechatImageKeyScanProgress>(delegate(WechatImageKeyScanProgress wechatImageKeyScanProgress)
						{
							int value12 = ((wechatImageKeyScanProgress.TotalBytes > 0) ? Math.Clamp((int)(wechatImageKeyScanProgress.BytesScanned * 100 / wechatImageKeyScanProgress.TotalBytes), 0, 100) : 0);
							Console.Error.WriteLine($"{wechatImageKeyScanProgress.Stage}：进程 {wechatImageKeyScanProgress.ProcessId}，{value12}%");
						});
						string databasePath7 = WechatImageKeyResolver.FindAccountRoot(format2);
						WechatImageKeyResolution keyResolution = await new WechatImageKeyResolver().ResolveAsync(databasePath7, template, progress5, cancellation.Token);
						if (!keyResolution.Success || keyResolution.AesKey == null)
						{
							throw new CliEnvironmentException(keyResolution.Error ?? "没有找到图片解码密钥。");
						}
						bool onlyFailed = keyResolution.Source == WechatImageKeySource.ProtectedCache;
						if (onlyFailed)
						{
							Console.Error.WriteLine("已复用并验证当前 Windows 用户加密保存的账号图片密钥。");
						}
						WechatDecodedImage decoded;
						try
						{
							decoded = WechatImageV2Decoder.Decode(format2, keyResolution.AesKey, template.XorKey);
						}
						finally
						{
							CryptographicOperations.ZeroMemory(keyResolution.AesKey);
						}
						string path8 = ConfigurationLoader.ResolvePath(outputRoot);
						string format3 = Path.ChangeExtension(path8, decoded.Extension);
						if (File.Exists(format3))
						{
							throw new IOException("输出文件已经存在，为避免覆盖已停止：" + format3);
						}
						string directoryName6 = Path.GetDirectoryName(format3);
						if (!string.IsNullOrEmpty(directoryName6))
						{
							ProtectedFileSystem.CreateDirectory(directoryName6);
						}
						await ProtectedFileSystem.WriteAllBytesAsync(format3, decoded.Bytes, cancellation.Token);
						appLogger.Log(AppLogLevel.Information, "WECHAT_IMAGE_PROBE_SUCCEEDED", "Program", "微信 V2 图片缓存已完成只读解码验证。", new Dictionary<string, object>
						{
							["format"] = decoded.MediaType,
							["byteSize"] = decoded.Bytes.Length,
							["processId"] = keyResolution.ScannedProcessId,
							["keyCacheUsed"] = onlyFailed,
							["keySource"] = keyResolution.Source.ToString(),
							["accountRootResolved"] = databasePath7 != null
						});
						if (WantsJson(args, invocation, "debug image-decode"))
						{
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								path = format3,
								format = decoded.MediaType,
								byteSize = decoded.Bytes.Length,
								keyCacheUsed = onlyFailed,
								keySource = keyResolution.Source.ToString(),
								processId = keyResolution.ScannedProcessId
							}, CliJson.Options));
						}
						else
						{
							Console.WriteLine($"验证成功：{decoded.MediaType}，{decoded.Bytes.Length} 字节，已写入 {format3}");
						}
						return 0;
					}
					case "attachments import":
					{
						string format3 = ReadOption(args, "--message-id") ?? throw new ArgumentException("attachments import 必须提供 --message-id。");
						string databasePath7 = ReadOption(args, "--asset-id") ?? throw new ArgumentException("attachments import 必须提供 --asset-id。");
						string format2 = ReadOption(args, "--file") ?? throw new ArgumentException("attachments import 必须提供 --file。");
						string databasePath8 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						string outputRoot = ConfigurationLoader.ResolvePath(options.MediaDirectory, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath8, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						MediaAsset mediaAsset = (await store.GetMediaAssetAsync(format3, databasePath7, cancellation.Token)) ?? throw new CliUsageException("指定消息下不存在对应媒体资产：请核对 --message-id 与 --asset-id（可用 attachments list 查）。");
						AttachmentImportService importer = new AttachmentImportService(options.EnableAttachmentImport, outputRoot, options.AttachmentMaximumFileBytes, options.AttachmentMaximumTotalBytes);
						AttachmentImportResult imported = null;
						try
						{
							imported = await importer.ImportAsync(format2, mediaAsset.AssetId, cancellation.Token);
							await store.RecordAttachmentImportAsync(format3, databasePath7, imported, cancellation.Token);
							if (WantsJson(args, invocation, "attachments import"))
							{
								Console.WriteLine(JsonSerializer.Serialize(new
								{
									RelativePath = imported.RelativePath,
									ByteSize = imported.ByteSize,
									Sha256 = imported.Sha256,
									messageId = format3,
									assetId = databasePath7
								}, CliJson.Options));
							}
							else
							{
								Console.WriteLine($"附件已安全导入：{imported.RelativePath}；{imported.ByteSize} 字节；SHA-256 {imported.Sha256}");
							}
							return 0;
						}
						catch (Exception ex6) when (!(ex6 is OperationCanceledException))
						{
							if ((object)imported != null)
							{
								importer.Rollback(imported);
							}
							await store.RecordAttachmentFailureAsync(format3, databasePath7, ex6.GetType().Name, CancellationToken.None);
							throw;
						}
					}
					case "attachments list":
					{
						MediaAcquisitionStatus? status = ParseAttachmentStatus(ReadOption(args, "--status"));
						string databasePath17 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						string outputRoot = ConfigurationLoader.ResolvePath(options.MediaDirectory, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath17, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<AttachmentRecord> records = await store.QueryAttachmentsAsync(null, cancellation.Token);
						AttachmentInventoryReport attachmentInventoryReport = new AttachmentInventoryService(outputRoot).BuildReport(records);
						Console.WriteLine(JsonSerializer.Serialize(new
						{
							Summary = attachmentInventoryReport.Summary,
							Records = attachmentInventoryReport.Records.Where((AttachmentRecord record) => !status.HasValue || record.Status == status).ToArray(),
							Issues = attachmentInventoryReport.Issues,
							Mode = "preview-only"
						}, CliJson.Options));
						return 0;
					}
					case "attachments candidates":
					{
						string outputRoot = ReadOption(args, "--source-dir") ?? options.AttachmentSourceDirectory;
						if (string.IsNullOrWhiteSpace(outputRoot))
						{
							throw new ArgumentException("未配置微信文件目录：请用 --source-dir 指定（如 <微信文件目录>\\xwechat_files），或先用 config set --name AttachmentSourceDirectory --value <目录> 写入配置。");
						}
						MediaAcquisitionStatus? candidateStatus = ParseAttachmentStatus(ReadOption(args, "--status"));
						string text12 = ReadOption(args, "--limit");
						int num4;
						if (text12 != null)
						{
							if (!int.TryParse(text12, out var result4) || result4 < 1 || result4 > 1000)
							{
								throw new ArgumentException("--limit 必须在 1 到 1000 之间。");
							}
							num4 = result4;
						}
						else
						{
							num4 = 50;
						}
						int count = num4;
						string format2 = ResolveOutputFormat(args, invocation, "table");
						string text13 = format2;
						if ((!(text13 == "table") && !(text13 == "json")) || 1 == 0)
						{
							throw new ArgumentException("不支持的格式：" + format2 + "。可选：table、json。");
						}
						string messageId = ReadOption(args, "--message-id");
						string assetId = ReadOption(args, "--asset-id");
						if (messageId == null != (assetId == null))
						{
							throw new ArgumentException("--message-id 与 --asset-id 必须同时提供（或都不提供以批量扫描）。");
						}
						string databasePath2 = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath2, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						AttachmentSourceCandidateService candidateService = new AttachmentSourceCandidateService(ConfigurationLoader.ResolvePath(outputRoot), options.AttachmentSourceSearchSubdirectories);
						try
						{
							IReadOnlyList<(AttachmentRecord, AttachmentCandidateSearchResult)> readOnlyList;
							if (messageId != null && assetId != null)
							{
								AttachmentRecord attachmentRecord = (await store.QueryAttachmentsAsync(null, cancellation.Token)).FirstOrDefault((AttachmentRecord attachmentRecord3) => string.Equals(attachmentRecord3.MessageId, messageId, StringComparison.Ordinal) && string.Equals(attachmentRecord3.AssetId, assetId, StringComparison.Ordinal)) ?? throw new ArgumentException($"指定消息下不存在对应媒体资产：--message-id {messageId} --asset-id {assetId}。");
								readOnlyList = new _003C_003Ez__ReadOnlySingleElementList<(AttachmentRecord, AttachmentCandidateSearchResult)>((attachmentRecord, candidateService.FindCandidates(attachmentRecord.OriginalName, null, attachmentRecord.ByteSize, attachmentRecord.DisplaySize, attachmentRecord.ObservedAt)));
							}
							else
							{
								readOnlyList = (from record in (await store.QueryAttachmentsAsync(candidateStatus, cancellation.Token)).Take(count).ToArray()
									select (record: record, candidateService.FindCandidates(record.OriginalName, null, record.ByteSize, record.DisplaySize, record.ObservedAt))).ToArray();
							}
							appLogger.Log(AppLogLevel.Information, "CLI_ATTACHMENT_CANDIDATES_SCANNED", "Program", "已在微信文件目录里只读查找附件候选。", new Dictionary<string, object>
							{
								["scanned"] = readOnlyList.Count,
								["indexedFileCount"] = candidateService.IndexedFileCount,
								["layout"] = candidateService.Layout.ToString(),
								["withCandidates"] = readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Candidates.Count > 0),
								["highConfidence"] = readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Confidence == AttachmentCandidateConfidence.High),
								["sourceConfigured"] = !string.IsNullOrWhiteSpace(options.AttachmentSourceDirectory)
							});
							var value2 = new
							{
								sourceDirectory = candidateService.SourceDirectory,
								layout = candidateService.Layout.ToString(),
								indexedFileCount = candidateService.IndexedFileCount,
								statusFilter = candidateStatus?.ToString(),
								scanned = readOnlyList.Count,
								withCandidates = readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Candidates.Count > 0),
								highConfidence = readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Confidence == AttachmentCandidateConfidence.High),
								mode = "preview-only",
								items = readOnlyList.Select(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => new
								{
									MessageId = tuple2.Record.MessageId,
									AssetId = tuple2.Record.AssetId,
									Conversation = tuple2.Record.Conversation,
									ObservedAt = tuple2.Record.ObservedAt,
									Kind = tuple2.Record.Kind,
									OriginalName = tuple2.Record.OriginalName,
									DisplaySize = tuple2.Record.DisplaySize,
									ByteSize = tuple2.Record.ByteSize,
									Status = tuple2.Record.Status,
									LocalPath = tuple2.Record.LocalPath,
									confidence = tuple2.Result.Confidence.ToString(),
									highConfidence = tuple2.Result.HighConfidence,
									suggestedPath = tuple2.Result.SuggestedCandidate?.FullPath,
									suggestedScore = tuple2.Result.SuggestedCandidate?.Score,
									candidateCount = tuple2.Result.Candidates.Count,
									candidates = tuple2.Result.Candidates
								}).ToArray()
							};
							if (format2 == "json")
							{
								Console.WriteLine(JsonSerializer.Serialize(value2, CliJson.Options));
							}
							else
							{
								Console.WriteLine($"来源目录：{candidateService.SourceDirectory}（布局 {candidateService.Layout}，已索引 {candidateService.IndexedFileCount} 个文件）");
								Console.WriteLine($"扫描 {readOnlyList.Count} 条资产：有候选 {readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Candidates.Count > 0)} 条，高置信 {readOnlyList.Count<(AttachmentRecord, AttachmentCandidateSearchResult)>(((AttachmentRecord Record, AttachmentCandidateSearchResult Result) tuple2) => tuple2.Result.Confidence == AttachmentCandidateConfidence.High)} 条。");
								foreach (var (attachmentRecord2, attachmentCandidateSearchResult) in readOnlyList)
								{
									Console.WriteLine($"  {attachmentRecord2.OriginalName ?? "(无文件名)"} | {attachmentCandidateSearchResult.Confidence} | 候选 {attachmentCandidateSearchResult.Candidates.Count}" + (((object)attachmentCandidateSearchResult.SuggestedCandidate == null) ? string.Empty : (" | 建议 " + attachmentCandidateSearchResult.SuggestedCandidate.FullPath)));
								}
								Console.WriteLine("仅预览：本命令不复制、不修改、不删除任何来源文件；导入请用 attachments import。");
							}
							return 0;
						}
						finally
						{
							if (candidateService != null)
							{
								((IDisposable)candidateService).Dispose();
							}
						}
					}
					case "health":
					{
						SqliteMessageStore store2 = new SqliteMessageStore(ResolveDatabasePath(databaseOverride, options, settingsDirectory), options.BackupRetentionCount);
						ApplicationHealthSnapshot applicationHealthSnapshot = await new ApplicationHealthService(options, store2, ConfigurationLoader.ResolvePath(options.LogDirectory, settingsDirectory), ConfigurationLoader.ResolvePath(options.MediaDirectory, settingsDirectory)).ReadAsync(cancellation.Token);
						Console.WriteLine(JsonSerializer.Serialize(applicationHealthSnapshot, CliJson.Options));
						return (!applicationHealthSnapshot.Database.IntegrityOk || applicationHealthSnapshot.Database.SchemaVersion != applicationHealthSnapshot.Database.TargetSchemaVersion) ? 6 : 0;
					}
					case "config show":
					{
						bool flag4 = CliOptionReader.IsPresent(args, "--redact");
						AppOptions options2 = (flag4 ? options with
						{
							MonitoredConversationWhitelist = Array.Empty<string>(),
							UnreadConversationWhitelist = Array.Empty<string>(),
							HistoryBackfillConversationWhitelist = Array.Empty<string>(),
							MergedForwardConversationWhitelist = Array.Empty<string>(),
							AvatarSenderConversationWhitelist = Array.Empty<string>(),
							AttachmentSourceDirectory = string.Empty
						} : options);
						var value10 = new
						{
							settingsPath = text5,
							settingsDirectory = settingsDirectory,
							profileName = profile.Name,
							resolvedPaths = new
							{
								database = ResolveDatabasePath(databaseOverride, options, settingsDirectory),
								jsonlOutput = ConfigurationLoader.ResolvePath(options.JsonlOutputPath, settingsDirectory),
								logDirectory = ConfigurationLoader.ResolvePath(options.LogDirectory, settingsDirectory),
								mediaDirectory = ConfigurationLoader.ResolvePath(options.MediaDirectory, settingsDirectory),
								avatarCatalog = ConfigurationLoader.ResolvePath(options.AvatarCatalogPath, settingsDirectory)
							},
							cliOverrides = new
							{
								settings = invocation.Settings,
								profile = invocation.Profile,
								database = invocation.Database,
								logLevel = invocation.LogLevel,
								quiet = invocation.Quiet,
								json = invocation.Json,
								allowInteraction = invocation.AllowInteraction,
								noInteraction = invocation.NoInteraction
							},
							interaction = new
							{
								allowWeChatInteraction = options.AllowWeChatInteraction,
								enableMonitoredConversationOpening = options.EnableMonitoredConversationOpening,
								enableUnreadConversationOpening = options.EnableUnreadConversationOpening,
								enableMouseClickFallbackForWhitelist = options.EnableMouseClickFallbackForWhitelist,
								enableWindowMessageClickFallbackForWhitelist = options.EnableWindowMessageClickFallbackForWhitelist,
								enableMergedForwardExpansion = options.EnableMergedForwardExpansion,
								enableHistoryBackfill = options.EnableHistoryBackfill
							},
							whitelistCounts = new
							{
								monitoredConversation = options.MonitoredConversationWhitelist.Length,
								unreadConversation = options.UnreadConversationWhitelist.Length,
								historyBackfillConversation = options.HistoryBackfillConversationWhitelist.Length,
								mergedForwardConversation = options.MergedForwardConversationWhitelist.Length,
								avatarSenderConversation = options.AvatarSenderConversationWhitelist.Length
							},
							redacted = flag4,
							options = options2
						};
						appLogger.Log(AppLogLevel.Information, "CLI_CONFIG_DUMPED", "Program", "已输出生效配置。", new Dictionary<string, object>
						{
							["profileName"] = profile.Name,
							["redacted"] = flag4,
							["allowWeChatInteraction"] = options.AllowWeChatInteraction,
							["monitoredWhitelistCount"] = options.MonitoredConversationWhitelist.Length
						});
						Console.WriteLine(JsonSerializer.Serialize(value10, CliJson.Options));
						return 0;
					}
					case "config set":
					{
						string text16 = ReadOption(args, "--name") ?? throw new ArgumentException("config set 必须提供 --name 属性名，例如 --name DatabasePath。用 config show 查看全部可用项。");
						string text17 = ReadOption(args, "--value") ?? throw new ArgumentException("config set 必须提供 --value 新值。清空字符串数组可写 --value= ”（空值）。");
						if (CliOptionReader.IsPresent(args, "--dry-run"))
						{
							PropertyInfo propertyInfo = typeof(AppOptions).GetProperty(text16, BindingFlags.IgnoreCase | BindingFlags.Instance | BindingFlags.Public) ?? throw new ArgumentException($"未知的配置项：{text16}。用 config show 查看全部 {ConfigurationLoader.OptionPropertyCount} 个可用项。");
							if (propertyInfo.Name == "BackupRetentionCount")
							{
								if (!int.TryParse(text17, out var result7))
								{
									throw new ArgumentException("备份保留数量必须为整数。");
								}
								BackupRetention.ValidateCount(result7);
							}
							Console.WriteLine(JsonSerializer.Serialize(new
							{
								settingsPath = text5,
								propertyName = propertyInfo.Name,
								propertyType = propertyInfo.PropertyType.Name,
								requestedValue = text17,
								dryRun = true,
								written = false
							}, CliJson.Options));
							return 0;
						}
						ConfigurationPatchResult configurationPatchResult = OperatingSystem.IsMacOS()
							? ConfigurationLoader.PatchOption(text5, text16, text17, "records.db")
							: ConfigurationLoader.PatchOption(text5, text16, text17);
						appLogger.Log(AppLogLevel.Information, "CLI_CONFIG_PATCHED", "Program", "已定点修改一个配置项。", new Dictionary<string, object>
						{
							["propertyName"] = configurationPatchResult.PropertyName,
							["createdFile"] = configurationPatchResult.CreatedFile,
							["hadPreviousValue"] = configurationPatchResult.OldValue != null
						});
						Console.WriteLine(JsonSerializer.Serialize(new
						{
							SettingsPath = configurationPatchResult.SettingsPath,
							PropertyName = configurationPatchResult.PropertyName,
							oldValue = configurationPatchResult.OldValue,
							NewValue = configurationPatchResult.NewValue,
							CreatedFile = configurationPatchResult.CreatedFile,
							dryRun = false,
							written = true
						}, CliJson.Options));
						Console.Error.WriteLine($"已写入 {configurationPatchResult.SettingsPath}；{configurationPatchResult.PropertyName} 的新值在下次启动或下一次命令调用时生效。");
						return 0;
					}
					case "diagnostics export":
					{
						string path2 = ReadOption(args, "--output") ?? throw new ArgumentException("diagnostics 必须提供 --output 输出 ZIP 路径，例如 --output diagnostics.zip。");
						string text11 = ReadOption(args, "--log-lines");
						int num2;
						if (text11 != null)
						{
							if (!int.TryParse(text11, out var result3) || result3 < 1 || result3 > 20000)
							{
								throw new ArgumentException("--log-lines 必须在 1 到 20000 之间。");
							}
							num2 = result3;
						}
						else
						{
							num2 = 500;
						}
						int num3 = num2;
						string format2 = ConfigurationLoader.ResolvePath(path2);
						string logDirectory = ConfigurationLoader.ResolvePath(options.LogDirectory, settingsDirectory);
						IReadOnlyList<AppLogRecord> recentLogs = (appLogger as IRecentLogSource)?.GetRecent(num3) ?? Array.Empty<AppLogRecord>();
						IReadOnlyList<string> onDiskLogTail = DiagnosticBundleContext.ReadOnDiskLogTail(logDirectory, num3);
						ApplicationHealthSnapshot health = null;
						string outputRoot = null;
						try
						{
							health = await new ApplicationHealthService(options, new SqliteMessageStore(ResolveDatabasePath(databaseOverride, options, settingsDirectory), options.BackupRetentionCount), logDirectory, ConfigurationLoader.ResolvePath(options.MediaDirectory, settingsDirectory)).ReadAsync(cancellation.Token);
						}
						catch (Exception ex3) when (!(ex3 is OperationCanceledException))
						{
							outputRoot = ex3.GetType().Name;
						}
						WeChatEnvironmentProbe.EnvironmentSnapshot environment = null;
						try
						{
							environment = WeChatEnvironmentProbe.Capture(profile);
						}
						catch (Exception ex4) when (!(ex4 is OperationCanceledException))
						{
						}
						Dictionary<string, object> healthSnapshot = DiagnosticBundleContext.BuildHealthSnapshot(appLogger, profile.Name, environment, new Dictionary<string, object>
						{
							["host"] = "cli",
							["command"] = command.ToLowerInvariant(),
							["healthReadError"] = outputRoot,
							["officialAccountArticles"] = health?.OfficialAccount.TotalArticleCount,
							["officialAccountArticleCounts"] = health?.OfficialAccount.ArticleCounts,
							["officialAccountCursors"] = health?.OfficialAccount.Cursors,
							["officialAccountCredentials"] = health?.OfficialAccount.Credentials
						});
						DiagnosticBundleResult diagnosticBundleResult = OperatingSystem.IsMacOS()
							? MacDiagnosticExport.Create(format2, text5, ResolveDatabasePath(databaseOverride, options, settingsDirectory), macImports.ArchiveDirectory, options, recentLogs, onDiskLogTail, healthSnapshot, cancellation.Token)
							: DiagnosticBundleBuilder.Create(format2, options, recentLogs, onDiskLogTail, healthSnapshot);
						appLogger.Log(AppLogLevel.Information, "CLI_DIAGNOSTIC_BUNDLE_EXPORTED", "Program", "已导出脱敏诊断包。", new Dictionary<string, object>
						{
							["entryCount"] = diagnosticBundleResult.EntryCount,
							["logRecordCount"] = diagnosticBundleResult.LogRecordCount,
							["onDiskLogTailLines"] = onDiskLogTail.Count,
							["healthReadError"] = outputRoot
						});
						Console.WriteLine(JsonSerializer.Serialize(new
						{
							path = diagnosticBundleResult.Path,
							entryCount = diagnosticBundleResult.EntryCount,
							logRecordCount = diagnosticBundleResult.LogRecordCount,
							onDiskLogTailLines = onDiskLogTail.Count,
							recentLogRecords = recentLogs.Count,
							healthReadError = outputRoot
						}, CliJson.Options));
						return 0;
					}
					case "debug group-window":
					{
						string path6 = ReadOption(args, "--output") ?? "ui-tree-group-members.txt";
						string outputRoot = ConfigurationLoader.ResolvePath(path6);
						string directoryName5 = Path.GetDirectoryName(outputRoot);
						if (!string.IsNullOrEmpty(directoryName5))
						{
							ProtectedFileSystem.CreateDirectory(directoryName5);
						}
						if (profile.GroupInfoNavigation.Length == 0)
						{
							throw new CliEnvironmentException("profile 未配置 GroupInfoNavigation（打开群聊“聊天信息”面板的 UIA 路径）；空路径会直接返回微信主窗口，为避免误点主窗口已拒绝执行。");
						}
						using WeChatAutomationSession session = AttachWeChat(profile);
						session.Window.Focus();
						AutomationElement automationElement = new UiSelectorPath(profile.GroupInfoNavigation).FindFirst(session.Window);
						if (automationElement == null)
						{
							throw new CliEnvironmentException("未通过 profile 的 GroupInfoNavigation 路径找到“聊天信息”按钮。请先打开目标群聊；若微信已改版，请更新 profile 里的选择器。");
						}
						Window[] visibleWindows = (from window2 in session.Application.GetAllTopLevelWindows(session.Automation)
							where WeChatAutomationSession.SafeRead(() => !window2.IsOffscreen, fallback: false)
							select window2).Where(delegate(Window window2)
						{
							Rectangle rectangle = WeChatAutomationSession.SafeRead(() => window2.BoundingRectangle, default(Rectangle));
							return rectangle.Width > 100 && rectangle.Height > 100;
						}).ToArray();
						if (visibleWindows.Length <= 1)
						{
							automationElement.Click();
							await Task.Delay(1200, cancellation.Token);
							visibleWindows = (from window2 in session.Application.GetAllTopLevelWindows(session.Automation)
								where WeChatAutomationSession.SafeRead(() => !window2.IsOffscreen, fallback: false)
								select window2).Where(delegate(Window window2)
							{
								Rectangle rectangle = WeChatAutomationSession.SafeRead(() => window2.BoundingRectangle, default(Rectangle));
								return rectangle.Width > 100 && rectangle.Height > 100;
							}).ToArray();
						}
						await using (FileStream stream = new FileStream(ProtectedFileSystem.OpenPath(outputRoot, FileAccess.Write), FileMode.Create, FileAccess.Write, FileShare.Read))
						{
							int num11;
							await using (StreamWriter writer = new StreamWriter(stream))
							{
								Window[] array = visibleWindows;
								foreach (Window window in array)
								{
									await writer.WriteLineAsync($"=== Window Name=\"{WeChatAutomationSession.SafeRead(() => window.Name, string.Empty)}\" Class=\"{WeChatAutomationSession.SafeRead(() => window.ClassName, string.Empty)}\" ===");
									await CompactUiTreeDumper.DumpAsync(window, writer, 24, 5000, cancellation.Token);
								}
								if (WantsJson(args, invocation, "debug group-window"))
								{
									Console.WriteLine(JsonSerializer.Serialize(new
									{
										path = outputRoot,
										windowCount = visibleWindows.Length
									}, CliJson.Options));
								}
								else
								{
									Console.WriteLine("群聊信息探测 UI 树已写入：" + outputRoot);
								}
								num11 = 0;
							}
							num5 = num11;
						}
						return num5;
					}
					case "debug group-members":
					{
						using WeChatAutomationSession session = AttachWeChat(profile);
						session.Window.Focus();
						GroupMemberSnapshot snapshot = await new GroupMemberReader().ReadAllAsync(session.Window, cancellation.Token);
						string text33 = JsonSerializer.Serialize(snapshot, CliJson.Options);
						string text34 = ReadOption(args, "--output");
						if (text34 == null)
						{
							Console.WriteLine(text33);
						}
						else
						{
							string outputRoot = ConfigurationLoader.ResolvePath(text34);
							string directoryName4 = Path.GetDirectoryName(outputRoot);
							if (!string.IsNullOrEmpty(directoryName4))
							{
								ProtectedFileSystem.CreateDirectory(directoryName4);
							}
							await ProtectedFileSystem.WriteAllTextAsync(outputRoot, text33, cancellation.Token);
							Console.WriteLine($"已提取 {snapshot.Members.Count}/{snapshot.ExpectedCount?.ToString() ?? "?"} 位成员：{outputRoot}");
						}
						return (!snapshot.IsComplete) ? 6 : 0;
					}
					case "debug avatar-match":
					{
						using WeChatAutomationSession session = AttachWeChat(profile);
						session.Window.Focus();
						string text29 = ReadOption(args, "--debug-dir");
						string outputRoot = ((text29 == null) ? null : ConfigurationLoader.ResolvePath(text29));
						GroupAvatarCatalogReader catalogReader = new GroupAvatarCatalogReader(outputRoot);
						IReadOnlyList<GroupMemberAvatar> catalog = await catalogReader.ReadAllAsync(session.Window, cancellation.Token);
						await catalogReader.CloseInfoAsync(session.Window, cancellation.Token);
						string text30 = ReadOption(args, "--catalog-output");
						if (text30 != null)
						{
							new AvatarCatalogStore(ConfigurationLoader.ResolvePath(text30)).Save(new AvatarCatalogDocument(new MessageSnapshotReader(profile).Read(session.Window).Conversation, catalog, DateTimeOffset.UtcNow));
						}
						ConversationSnapshot conversationSnapshot = new MessageSnapshotReader(profile).Read(session.Window);
						AutomationElement? obj9 = ((profile.MessageContainer == null) ? null : ElementSearch.FindFirst(session.Window, profile.MessageContainer, 20, 8000));
						if (obj9 == null || profile.MessageItem == null)
						{
							throw new CliEnvironmentException("Profile 未配置消息列表或消息项选择器。");
						}
						IReadOnlyList<AutomationElement> source3 = ElementSearch.FindAll(obj9, profile.MessageItem, 8, 10000);
						AvatarSenderMatcher avatarSenderMatcher = new AvatarSenderMatcher();
						List<SenderProbeEntry> list = new List<SenderProbeEntry>();
						NativeWindowCapture messageFrame = NativeWindowCapture.Create(session.Window);
						try
						{
							foreach (ObservedMessage message in conversationSnapshot.Messages)
							{
								AutomationElement item = source3.FirstOrDefault(delegate(AutomationElement candidate)
								{
									Rectangle rectangle = WeChatAutomationSession.SafeRead(() => candidate.BoundingRectangle, default(Rectangle));
									return Math.Abs((double)rectangle.Top - message.Bounds.Top) < 1.0 && Math.Abs((double)rectangle.Height - message.Bounds.Height) < 1.0;
								});
								if (item == null)
								{
									continue;
								}
								using Bitmap bitmap = WeChatAutomationSession.SafeRead(() => messageFrame.Crop(item), null);
								if (bitmap != null)
								{
									AvatarSenderMatch avatarSenderMatch = avatarSenderMatcher.Match(bitmap, catalog);
									if (outputRoot != null)
									{
										ProtectedFileSystem.CreateDirectory(outputRoot);
										bitmap.Save(ProtectedFileSystem.OpenPath(Path.Combine(outputRoot, $"message-{list.Count:000}.png"), FileAccess.Write));
									}
									list.Add(new SenderProbeEntry(message.Content, avatarSenderMatch.Sender, avatarSenderMatch.Direction, avatarSenderMatch.Distance, avatarSenderMatch.Confidence, avatarSenderMatch.Margin, message.Bounds, new UiBounds(message.Bounds.Left + avatarSenderMatch.AvatarBounds.Left, message.Bounds.Top + avatarSenderMatch.AvatarBounds.Top, avatarSenderMatch.AvatarBounds.Width, avatarSenderMatch.AvatarBounds.Height)));
								}
							}
							string text31 = JsonSerializer.Serialize(new SenderProbeResult(conversationSnapshot.Conversation, catalog.Select((GroupMemberAvatar member) => member.Name).Distinct<string>(StringComparer.Ordinal).ToArray(), list, DateTimeOffset.Now), CliJson.Options);
							string text32 = ReadOption(args, "--output");
							if (text32 == null)
							{
								Console.WriteLine(text31);
							}
							else
							{
								string format2 = ConfigurationLoader.ResolvePath(text32);
								string directoryName3 = Path.GetDirectoryName(format2);
								if (!string.IsNullOrEmpty(directoryName3))
								{
									ProtectedFileSystem.CreateDirectory(directoryName3);
								}
								await ProtectedFileSystem.WriteAllTextAsync(format2, text31, cancellation.Token);
								Console.WriteLine("头像发送者探测已输出：" + format2);
							}
							return 0;
						}
						finally
						{
							if (messageFrame != null)
							{
								((IDisposable)messageFrame).Dispose();
							}
						}
					}
					case "timeline query":
					{
						string value = ReadOption(args, "--from") ?? throw new ArgumentException("timeline query 需要 --from，例如 --from \"2026-08-10 14:00\"。");
						string text6 = ReadOption(args, "--to");
						DateTimeOffset from = ParseLocalTime(value, "--from");
						DateTimeOffset to = ((text6 == null) ? DateTimeOffset.Now : ParseLocalTime(text6, "--to"));
						if (from > to)
						{
							throw new ArgumentException("--from 不能晚于 --to。");
						}
						string text7 = (ReadOption(args, "--source") ?? "all").ToLowerInvariant();
						TimelineSource timelineSource;
						switch (text7)
						{
						case "all":
							timelineSource = TimelineSource.All;
							break;
						case "messages":
						case "message":
							timelineSource = TimelineSource.Messages;
							break;
						case "sessions":
						case "session":
							timelineSource = TimelineSource.Sessions;
							break;
						default:
							throw new ArgumentException("不支持的来源：" + text7 + "。可选：all、messages、sessions。");
						}
						TimelineSource source = timelineSource;
						string databasePath = ResolveDatabasePath(databaseOverride, options, settingsDirectory);
						SqliteMessageStore store = new SqliteMessageStore(databasePath, options.BackupRetentionCount);
						await store.InitializeAsync(cancellation.Token);
						IReadOnlyList<TimelineEntry> entries = await store.QueryTimelineAsync(new TimelineQuery(from, to, ReadOption(args, "--conversation"), ReadOption(args, "--keyword"), source), cancellation.Token);
						string format = ResolveOutputFormat(args, invocation, "markdown");
						string text8 = ReadOption(args, "--include-metadata");
						int num;
						if (text8 != null)
						{
							if (!bool.TryParse(text8, out var result2))
							{
								throw new ArgumentException("--include-metadata 必须是 true 或 false。");
							}
							num = (result2 ? 1 : 0);
						}
						else
						{
							num = 1;
						}
						bool includeStructuredMetadata = (byte)num != 0;
						string text9 = TimelineFormatter.Format(entries, format, includeStructuredMetadata);
						string text10 = ReadOption(args, "--output");
						if (text10 == null)
						{
							Console.WriteLine(text9);
						}
						else
						{
							string outputRoot = ConfigurationLoader.ResolvePath(text10);
							string directoryName = Path.GetDirectoryName(outputRoot);
							if (!string.IsNullOrEmpty(directoryName))
							{
								ProtectedFileSystem.CreateDirectory(directoryName);
							}
							await ProtectedFileSystem.WriteAllTextAsync(outputRoot, text9, cancellation.Token);
							Console.WriteLine($"已输出 {entries.Count} 条记录：{outputRoot}");
						}
						Console.Error.WriteLine($"查询到 {entries.Count} 条记录。时间依据为 observedAt（采集器观察时间）。");
						return 0;
					}
					default:
						Console.Error.WriteLine("未知命令：" + command);
						Console.WriteLine(CliHelpText.Render());
						return 2;
					}
				}
				finally
				{
					if (cancellation != null)
					{
						((IDisposable)cancellation).Dispose();
					}
				}
			}
			catch (OperationCanceledException)
			{
				appLogger?.Log(AppLogLevel.Information, "APPLICATION_CANCELLED", "Program", "用户请求停止程序；已安全写入的断点或游标可用于续传。");
				return 130;
			}
			catch (CliUsageException ex8)
			{
				ReportUsageError(ex8.Message);
				return 2;
			}
			catch (CliEnvironmentException ex9)
			{
				appLogger?.Log(AppLogLevel.Warning, "CLI_ENVIRONMENT_UNAVAILABLE", "Program", "命令所需的环境不满足。", new Dictionary<string, object> { ["command"] = command.ToLowerInvariant() });
				Console.Error.WriteLine(ex9.Message);
				if (CliErrorEnvelope.RequestsJson(args))
				{
					CliErrorEnvelope.Write(Console.Out, "environmentUnavailable", ex9.Message);
				}
				return 3;
			}
			catch (ProtectedSourcePathException ex10)
			{
				ReportUsageError(ex10.Message);
				return 2;
			}
			catch (ArgumentException ex11)
			{
				ReportUsageError(ex11.Message);
				return 2;
			}
			catch (Exception ex12)
			{
				appLogger?.Log(AppLogLevel.Error, "APPLICATION_FAILED", "Program", "命令执行失败。", null, ex12);
				Console.Error.WriteLine(ex12.Message);
				return 1;
			}
			finally
			{
				UiAutomationFailureAggregator.Flush();
				UiAutomationFailureAggregator.Reset();
				appLogger?.Dispose();
			}
		}
		static AppOptions ApplyCliOverrides(AppOptions appOptions4, CliInvocation cli)
		{
			string text40 = cli.LogLevel ?? appOptions4.MinimumLogLevel;
			bool flag6 = !cli.NoInteraction && (cli.AllowInteraction || appOptions4.AllowWeChatInteraction);
			if (!string.Equals(text40, appOptions4.MinimumLogLevel, StringComparison.OrdinalIgnoreCase) || flag6 != appOptions4.AllowWeChatInteraction)
			{
				return appOptions4 with
				{
					MinimumLogLevel = text40,
					AllowWeChatInteraction = flag6
				};
			}
			return appOptions4;
		}
		static WeChatAutomationSession AttachWeChat(WeChatUiProfile profile2)
		{
			try
			{
				return WeChatAutomationSession.Attach(profile2);
			}
			catch (InvalidOperationException ex13)
			{
				throw new CliEnvironmentException(ex13.Message, ex13);
			}
		}
		static DateTimeOffset EndOfDayLocal(DateOnly date)
		{
			return CliValueParser.EndOfDayLocal(date);
		}
		static OfficialAccountDateRange? ParseArticleDateRange(IReadOnlyList<string> arguments)
		{
			string text40 = ReadOption(arguments, "--from");
			string text41 = ReadOption(arguments, "--to");
			if (text40 == null && text41 == null)
			{
				return null;
			}
			DateOnly start = ((text40 == null) ? DateOnly.MinValue : ParseDateOnly(text40, "--from"));
			DateOnly end = ((text41 == null) ? DateOnly.FromDateTime(DateTime.Now) : ParseDateOnly(text41, "--to"));
			return new OfficialAccountDateRange(start, end);
		}
		static MediaAcquisitionStatus? ParseAttachmentStatus(string? text41)
		{
			string text40 = (text41 ?? "all").ToLowerInvariant();
			return text40 switch
			{
				"all" => null, 
				"metadata" => MediaAcquisitionStatus.MetadataOnly, 
				"available" => MediaAcquisitionStatus.Available, 
				"failed" => MediaAcquisitionStatus.Failed, 
				_ => throw new ArgumentException("不支持的附件状态：" + text40 + "。可选：all、metadata、available、failed。"), 
			};
		}
		static DateOnly ParseDateOnly(string value12, string optionName)
		{
			return CliValueParser.ParseDateOnly(value12, optionName);
		}
		static TimeSpan ParseDuration(string value12, string optionName)
		{
			return CliValueParser.ParseDuration(value12, optionName);
		}
		static DateTimeOffset ParseLocalTime(string value12, string optionName)
		{
			return CliValueParser.ParseLocalTime(value12, optionName);
		}
		static string? ReadOption(IReadOnlyList<string> arguments, string name2)
		{
			return CliOptionReader.Read(arguments, name2);
		}
		void ReportUsageError(string text40)
		{
			appLogger?.Log(AppLogLevel.Warning, "CLI_USAGE_ERROR", "Program", "命令行用法错误。", new Dictionary<string, object> { ["command"] = command.ToLowerInvariant() });
			Console.Error.WriteLine(text40);
			if (CliErrorEnvelope.RequestsJson(args))
			{
				CliErrorEnvelope.Write(Console.Out, "invalidArguments", text40);
			}
		}
		static string ResolveDatabasePath(string? text40, AppOptions appOptions4, string? relativeTo)
		{
			if (text40 != null)
			{
				return ConfigurationLoader.ResolvePath(text40);
			}
			return ConfigurationLoader.ResolvePath(appOptions4.DatabasePath, relativeTo);
		}
		static string ResolveOutputFormat(IReadOnlyList<string> arguments, CliInvocation cli, string defaultFormat)
		{
			string text40 = CliOptionReader.Read(arguments, "--format");
			if (text40 != null)
			{
				return text40.ToLowerInvariant();
			}
			if (!cli.Json)
			{
				return defaultFormat;
			}
			return "json";
		}
		static DateTimeOffset StartOfDayLocal(DateOnly date)
		{
			return CliValueParser.StartOfDayLocal(date);
		}
		static bool WantsJson(IReadOnlyList<string> arguments, CliInvocation cli, string commandName)
		{
			string text40 = ResolveOutputFormat(arguments, cli, "text");
			if ((!(text40 == "text") && !(text40 == "json")) || 1 == 0)
			{
				throw new ArgumentException(commandName + " 不支持格式：" + text40 + "。可选：text、json。");
			}
			return text40 == "json";
		}
	}
}
