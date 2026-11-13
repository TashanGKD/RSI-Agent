const $ = (id) => document.getElementById(id);
const state = {
  token: "", tasks: [], hasMore: false, task: null, report: null, before: null,
  changes: [], comparison: true, filter: "all", caseId: null, requestNumber: 0,
};

const labels = {
  pass: "通过", fail: "失败", unverified: "未验证", infrastructure_error: "环境错误",
  blocked: "关键项失败", incomplete: "评测未覆盖完整", completed: "评测完成",
};
const reasons = {
  wrong_action_order_or_count: "动作顺序或次数与规则不符",
  wrong_final_state: "最终状态与预期不符",
  unexpected_action: "出现规则未允许的动作",
  wrong_decision: "答复方式与预期不符",
  wrong_values: "答复数值或口径与预期不符",
  wrong_citations: "引用位置与预期不符",
  missing_observation: "本轮缺少观测记录",
  wrong_evidence_type: "观测类型与用例不匹配",
};
const operations = {
  approval: "确认批准", write: "写入数据", escalate: "转人工",
  skip_duplicate: "跳过重复事件", report_unavailable: "报告数据源不可用",
};
const decisions = { answer: "回答", abstain: "保留缺项", escalate: "转人工" };
const errors = {
  unauthorized: "访问令牌无效，或会话授权已变更。",
  task_storage_disabled: "服务尚未配置评测任务数据库。",
  task_not_found: "该评测任务不存在。",
  run_not_found: "未找到选中的评测版本。",
  task_id_in_use: "任务编号已存在，请换一个编号或打开原任务。",
  version_in_use: "该版本已有不同的观测记录，请使用新的被测版本。",
  evaluation_conditions_changed: "题集、材料快照或评测条件有变化，请另建任务。",
  material_snapshot_changed: "材料快照已变化，当前服务无法读取原轮次的原文。",
  material_or_location_not_found: "找不到这条引用对应的原文位置。",
  comparison_order: "整改前版本必须早于复测后版本。",
  invalid_task_input: "提交内容不符合评测接口，请检查题集、版本、条件编号及观测格式。",
  request_too_large: "提交内容超过服务允许的大小。",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action, className) {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function chip(value) {
  return element("span", labels[value] || value, "chip tone-" + value);
}

function setError(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

async function api(path, body) {
  const headers = { Authorization: "Bearer " + state.token };
  const options = { headers, cache: "no-store" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.method = "POST";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    const location = result.details?.[0]?.loc?.join(".");
    const message = errors[result.error] || "请求失败（HTTP " + response.status + "）。";
    throw new Error(location ? message + " 检查字段 " + location + "。" : message);
  }
  return result;
}

function taskPath(id) {
  return "/v1/tasks/" + encodeURIComponent(id);
}

function runPath(taskId, version) {
  return taskPath(taskId) + "/runs/" + encodeURIComponent(version);
}

function localTime(value) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function showTaskList() {
  const items = state.tasks.map((task) => {
    const item = button("", () => openTask(task.id), "task-item");
    item.setAttribute("aria-current", String(state.task?.id === task.id));
    item.append(
      element("strong", task.title),
      element("span", [task.version, labels[task.status], task.run_count + " 轮"].join(" · ")),
    );
    return item;
  });
  $("task-items").replaceChildren(...items);
  $("more-tasks").hidden = !state.hasMore;
}

async function loadTasks(append = false) {
  const offset = append ? state.tasks.length : 0;
  const data = await api("/v1/tasks?offset=" + offset);
  state.tasks = append ? state.tasks.concat(data.tasks) : data.tasks;
  state.hasMore = data.has_more;
  showTaskList();
}

function setVersions() {
  const runs = state.task.runs;
  const latest = runs[runs.length - 1].version;
  const earliest = runs[0].version;
  $("after").replaceChildren(...runs.map((run) => new Option(run.version, run.version)));
  $("after").value = latest;
  $("before").replaceChildren(...runs.slice(0, -1).map((run) => new Option(run.version, run.version)));
  $("before").value = earliest;
  state.comparison = runs.length > 1;
  $("view-comparison").disabled = runs.length < 2;
}

function adjustVersions() {
  const runs = state.task.runs;
  if (state.comparison && $("after").value === runs[0].version) $("after").value = runs[1].version;
  const afterIndex = $("after").selectedIndex;
  const preferred = $("before").value;
  const older = runs.slice(0, afterIndex);
  $("before").replaceChildren(...older.map((run) => new Option(run.version, run.version)));
  if (older.some((run) => run.version === preferred)) $("before").value = preferred;
  for (const option of $("after").options) {
    option.disabled = state.comparison && option.index === 0;
  }
  $("before-label").hidden = $("version-arrow").hidden = !state.comparison;
  $("after-caption").textContent = state.comparison ? "复测后" : "评测版本";
  $("view-report").setAttribute("aria-pressed", String(!state.comparison));
  $("view-comparison").setAttribute("aria-pressed", String(state.comparison));
}

async function openTask(id) {
  const request = ++state.requestNumber;
  const reopening = state.task?.id === id;
  setError("workspace-error");
  $("report").hidden = true;
  $("empty").hidden = true;
  try {
    const task = await api(taskPath(id));
    if (request !== state.requestNumber) return;
    state.task = task;
    if (!reopening) {
      state.filter = "all";
      state.caseId = null;
    }
    $("task-title").textContent = task.title;
    const url = new URL(window.location.href);
    url.searchParams.set("task", task.id);
    window.history.replaceState(null, "", url);
    setVersions();
    showTaskList();
    await loadReport();
  } catch (error) {
    if (request === state.requestNumber) setError("workspace-error", error.message);
  }
}

async function loadReport() {
  const request = ++state.requestNumber;
  adjustVersions();
  const before = $("before").value;
  const after = $("after").value;
  const id = state.task.id;
  $("report").hidden = false;
  $("report-status").textContent = "读取报告…";
  $("metrics").hidden = $("case-layout").hidden = true;
  $("export").disabled = $("retest").disabled = true;
  setError("workspace-error");
  try {
    if (state.comparison) {
      const query = new URLSearchParams({ before, after });
      const comparison = await api(taskPath(id) + "/comparison?" + query);
      if (request !== state.requestNumber) return;
      state.before = comparison.before;
      state.report = comparison.after;
      state.changes = comparison.changes;
    } else {
      const { report } = await api(runPath(id, after));
      if (request !== state.requestNumber) return;
      state.report = report;
      state.before = null;
      state.changes = [];
      if (state.filter === "changed") state.filter = "all";
    }
    const report = state.report;
    const synthetic = report.dataset_version.startsWith("synthetic-");
    $("report-context").textContent = synthetic ? "评测任务 / 合成样例" : "评测任务 / 运行报告";
    const when = state.task.runs.find((run) => run.version === after).created_at;
    $("task-meta").textContent = [
      "题集 " + report.dataset_version, "条件 " + report.conditions_id, "更新 " + localTime(when),
    ].join("  ·  ");
    const statusNodes = state.before ? [chip(state.before.status), document.createTextNode(" → ")] : [];
    $("report-status").replaceChildren(...statusNodes, chip(report.status));
    renderMetrics();
    renderCases();
    $("metrics").hidden = $("case-layout").hidden = false;
    $("export").disabled = $("retest").disabled = false;
  } catch (error) {
    if (request !== state.requestNumber) return;
    $("report-status").textContent = "报告暂不可用";
    setError("workspace-error", error.message);
  }
}

function renderMetrics() {
  const { before, report } = state;
  const cards = ["pass", "fail", "unverified", "infrastructure_error"].map((key) => {
    const card = element("div", null, "panel metric");
    const current = report.counts[key];
    const value = before ? before.counts[key] + " → " + current : String(current);
    const suffix = key === "fail"
      ? "其中关键项 " + report.cases.filter((item) => item.critical && item.status === "fail").length
      : key === "pass" ? "本轮已判定 " + report.scored + " / " + report.total
      : key === "unverified" ? "缺少观测或证据类型不符" : "与业务判定分别统计";
    card.append(element("div", labels[key], "metric-label"),
      element("strong", value, "metric-value tone-" + key), element("small", suffix));
    return card;
  });
  $("metrics").replaceChildren(...cards);
}

function renderCases() {
  const { report, before, changes } = state;
  const oldById = new Map((before?.cases || []).map((item) => [item.id, item]));
  const changed = new Set(changes.map((item) => item.id));
  const filters = [
    ["all", "全部 " + report.total],
    ...(before ? [["changed", "有变化 " + changed.size]] : []),
    ["attention", "待关注 " + report.cases.filter((item) => item.status !== "pass").length],
  ];
  const filterNodes = filters.map(([key, label]) => {
    const control = button(label, () => {
      state.filter = key;
      renderCases();
      $("filters").querySelector('[aria-pressed="true"]').focus();
    });
    control.setAttribute("aria-pressed", String(state.filter === key));
    return control;
  });
  $("filters").replaceChildren(...filterNodes);
  $("coverage").textContent = before
    ? "同一题集及评测条件 · " + changed.size + " 项状态变化"
    : "本轮判定 " + report.scored + " / " + report.total + " 项";
  const cases = report.cases.filter((item) => {
    if (state.filter === "changed") return changed.has(item.id);
    if (state.filter === "attention") return item.status !== "pass";
    return true;
  });
  if (!cases.some((item) => item.id === state.caseId)) {
    const focus = cases.find((item) => item.critical &&
      (item.status === "fail" || oldById.get(item.id)?.status === "fail"));
    state.caseId = (focus || cases[0])?.id;
  }
  const header = element("div", null, "case-head" + (before ? "" : " single"));
  header.append(element("span", "用例"));
  if (before) header.append(element("span", before.subject_version));
  header.append(element("span", report.subject_version));

  const rows = cases.map((item) => {
    const old = oldById.get(item.id);
    const row = button("", () => {
      state.caseId = item.id;
      for (const control of $("case-table").querySelectorAll(".case-row")) {
        control.setAttribute("aria-pressed", String(control === row));
      }
      renderEvidence(item, old);
    }, "case-row" + (before ? "" : " single"));
    row.setAttribute("aria-pressed", String(state.caseId === item.id));
    const title = element("span", item.scenario || item.id, "case-name");
    title.append(element("small", [
      item.kind === "qa" ? "问答" : "执行", item.rule, ...(item.critical ? ["关键用例"] : []),
    ].join(" · ")));
    row.append(title);
    if (old) row.append(chip(old.status));
    row.append(chip(item.status));
    return row;
  });
  $("case-table").replaceChildren(header, ...rows);
  const selected = cases.find((item) => item.id === state.caseId);
  if (selected) renderEvidence(selected, oldById.get(selected.id));
  else {
    $("case-table").append(element("p", "当前筛选下没有用例。", "inline-empty"));
    $("evidence").replaceChildren(element("h2", "用例证据", "panel-header"), element("p", "请选择其他筛选条件。", "inline-empty"));
    $("evidence").firstChild.id = "evidence-title";
  }
}

function actionList(actions) {
  if (!actions.length) return element("p", "无动作", "muted");
  const list = element("ol", null, "trace-list");
  for (const action of actions) {
    const item = element("li", operations[action.operation] || action.operation);
    item.append(element("small", action.target));
    list.append(item);
  }
  return list;
}

function traceCard(version, caseReport) {
  const card = element("div", null, "trace-card");
  const header = element("header");
  header.append(element("strong", version), chip(caseReport.status));
  card.append(header);
  if (caseReport.reasons.length) {
    card.append(element("p", caseReport.reasons.map((reason) => reasons[reason] || reason).join("、"), "result-why"));
  }
  const record = caseReport.evidence;
  if (record?.execution) {
    card.append(actionList(record.execution.events),
      element("p", "最终状态", "muted"),
      element("pre", JSON.stringify(record.execution.final_state, null, 2)));
  } else if (record?.answer) {
    card.append(element("p", decisions[record.answer.decision]));
    if (Object.keys(record.answer.values).length) {
      card.append(element("pre", JSON.stringify(record.answer.values, null, 2)));
    }
  } else {
    card.append(element("p", "没有可展示的问答或执行记录。", "muted"));
  }
  return card;
}

function renderEvidence(current, previous) {
  const title = element("h2", "用例证据");
  title.id = "evidence-title";
  const heading = element("header", null, "panel-header");
  const headingText = element("div");
  headingText.append(title, element("p", current.rule + " · " + current.id, "muted"));
  heading.append(headingText);
  const detail = element("div", null, "evidence-body");
  const traces = element("div", null, "trace-grid" + (previous ? "" : " single"));
  const report = state.report;
  const baseline = state.before;
  const taskId = state.task.id;
  if (previous) traces.append(traceCard(baseline.subject_version, previous));
  traces.append(traceCard(report.subject_version, current));

  const citations = new Map();
  function addReferences(refs, version, label) {
    for (const ref of refs) {
      const id = ref.asset_id + "/" + ref.location;
      if (!citations.has(id)) citations.set(id, { ref, version, label });
    }
  }
  addReferences(current.rule_sources || [], report.subject_version, "规则原文");
  addReferences(current.expected_citations, report.subject_version, "预期来源");
  addReferences(previous?.evidence?.answer?.citations || [], baseline?.subject_version, "整改前引用");
  addReferences(current.evidence?.answer?.citations || [], report.subject_version, "本轮引用");

  if (citations.size) {
    const block = element("div", null, "sources");
    const links = element("div", null, "passage-buttons");
    const passage = element("div", null, "passage");
    passage.hidden = true;
    passage.setAttribute("aria-live", "polite");
    let passageRequest = 0;
    for (const { ref, version, label } of citations.values()) {
      const refButton = button(label + " · " + ref.location, async () => {
        const request = ++passageRequest;
        passage.hidden = false;
        passage.textContent = "读取证据…";
        try {
          const query = new URLSearchParams({ location: ref.location });
          const data = await api(runPath(taskId, version) + "/evidence/" +
            encodeURIComponent(ref.asset_id) + "?" + query);
          if (request !== passageRequest) return;
          passage.replaceChildren(
            element("p", data.asset_id + " · " + data.location + " · " + version, "muted"),
            element("blockquote", data.text),
            element("p", "SHA-256 " + data.sha256 + (data.truncated ? " · 摘录已截断" : ""), "muted"),
          );
        } catch (error) {
          if (request === passageRequest) passage.textContent = error.message;
        }
      }, "quiet compact");
      links.append(refButton);
    }
    block.append(element("h3", "原文证据"), links, passage);
    detail.append(block);
  }
  detail.append(traces);

  const expected = element("div", null, "evidence-section");
  if (current.expected_execution) {
    expected.append(element("h3", "规则要求的执行顺序"), actionList(current.expected_execution.ordered_actions));
    detail.append(expected);
  } else if (current.expected_answer) {
    expected.append(element("h3", "预期答复"), element("p", decisions[current.expected_answer.decision]));
    if (Object.keys(current.expected_answer.values).length) {
      expected.append(element("pre", JSON.stringify(current.expected_answer.values, null, 2)));
    }
    detail.append(expected);
  }
  const suggestion = current.remediation || previous?.remediation;
  if (suggestion) {
    const block = element("div", null, "evidence-section");
    block.append(element("h3", "整改建议"), element("p", suggestion));
    detail.append(block);
  }
  $("evidence").replaceChildren(heading, detail);
}

async function connect(event) {
  event.preventDefault();
  state.token = $("token").value.trim();
  setError("connect-error");
  $("connect-form").querySelector("button").disabled = true;
  try {
    await loadTasks();
    $("token").value = "";
    $("connect").hidden = true;
    $("workspace").hidden = false;
    $("disconnect").hidden = false;
    $("connection-status").textContent = "评测服务已连接";
    $("connection-status").classList.add("ready");
    const target = new URLSearchParams(window.location.search).get("task") || state.tasks[0]?.id;
    if (target) await openTask(target);
    else $("empty").hidden = false;
  } catch (error) {
    state.token = "";
    setError("connect-error", error.message);
  } finally {
    $("connect-form").querySelector("button").disabled = false;
  }
}

async function openSubmission(retest) {
  setError("workspace-error");
  const active = retest ? state.report : null;
  try {
    const manifest = await api("/v1/cases");
    if (active && (manifest.id !== active.dataset_id || manifest.version !== active.dataset_version)) {
      throw new Error("当前服务使用了另一版题集，请为新条件发起评测。");
    }
    $("submit-title").textContent = retest ? "提交复测" : "发起评测";
    $("submit-help").textContent = retest
      ? "保留当前题集和条件编号，填写新版本及实际观测。"
      : "填写被测版本、条件编号和实际观测。缺少记录的用例将显示为未验证。";
    $("new-fields").hidden = retest;
    $("submit-task-title").required = $("submit-task-id").required = !retest;
    $("submit-task-title").value = "";
    $("submit-task-id").value = retest ? "" : "task-" + crypto.randomUUID().slice(0, 12);
    $("run-json").value = JSON.stringify({
      dataset_id: manifest.id, dataset_version: manifest.version, subject_version: "",
      conditions_id: active?.conditions_id || "", observations: [],
    }, null, 2);
    $("submission").dataset.task = retest ? state.task.id : "";
    setError("submit-error");
    $("submission").showModal();
  } catch (error) {
    setError("workspace-error", error.message);
  }
}

async function submit(event) {
  event.preventDefault();
  setError("submit-error");
  const activeId = $("submission").dataset.task;
  const newId = $("submit-task-id").value.trim();
  let run;
  try {
    run = JSON.parse($("run-json").value);
  } catch {
    setError("submit-error", "观测 JSON 格式无效。");
    return;
  }
  $("submit-run").disabled = $("close-dialog").disabled = true;
  try {
    const receipt = activeId
      ? await api(taskPath(activeId) + "/runs", run)
      : await api("/v1/tasks", { task_id: newId, title: $("submit-task-title").value, run });
    $("submission").close();
    $("run-json").value = "";
    await openTask(receipt.task_id);
    await loadTasks();
  } catch (error) {
    setError($("submission").open ? "submit-error" : "workspace-error", error.message);
  } finally {
    $("submit-run").disabled = $("close-dialog").disabled = false;
  }
}

function downloadReport() {
  const data = state.before
    ? { before: state.before, after: state.report, changes: state.changes }
    : state.report;
  const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = element("a");
  link.href = objectUrl;
  link.download = state.task.id + "-" + state.report.subject_version + ".json";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

$("connect-form").addEventListener("submit", connect);
$("submit-form").addEventListener("submit", submit);
$("close-dialog").addEventListener("click", () => $("submission").close());
$("submission").addEventListener("cancel", (event) => {
  if ($("submit-run").disabled) event.preventDefault();
});
$("submission").addEventListener("close", () => { $("run-json").value = ""; });
$("new-task").addEventListener("click", () => openSubmission(false));
$("retest").addEventListener("click", () => openSubmission(true));
$("export").addEventListener("click", downloadReport);
$("disconnect").addEventListener("click", () => window.location.reload());
$("refresh").addEventListener("click", async () => {
  setError("workspace-error");
  try {
    await loadTasks();
    const id = state.task?.id || state.tasks[0]?.id;
    if (id) await openTask(id);
    else $("empty").hidden = false;
  } catch (error) {
    setError("workspace-error", error.message);
  }
});
$("more-tasks").addEventListener("click", () => loadTasks(true).catch((error) => setError("workspace-error", error.message)));
$("before").addEventListener("change", loadReport);
$("after").addEventListener("change", loadReport);
$("view-report").addEventListener("click", () => {
  state.comparison = false;
  loadReport();
});
$("view-comparison").addEventListener("click", () => {
  state.comparison = true;
  loadReport();
});
$("fullscreen").hidden = !document.fullscreenEnabled;
$("fullscreen").addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    $("fullscreen").hidden = true;
  }
});
document.addEventListener("fullscreenchange", () => {
  $("fullscreen").textContent = document.fullscreenElement ? "退出全屏" : "全屏";
});
