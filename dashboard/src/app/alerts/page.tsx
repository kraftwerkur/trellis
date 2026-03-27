"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import {
  Bell, Plus, Trash2, ToggleLeft, ToggleRight, TestTube,
  CheckCircle2, AlertTriangle, XCircle, Clock, Send, X,
} from "lucide-react";

/* ─── Types ─── */

interface AlertRule {
  id: number;
  name: string;
  description: string;
  source: string;
  condition_type: string;
  condition_metric: string;
  condition_operator: string;
  condition_value: string;
  channels: string[];
  channel_config: Record<string, string>;
  severity: string;
  cooldown_minutes: number;
  active: boolean;
  agent_id_filter: string | null;
  created: string;
}

interface AlertEvent {
  id: number;
  rule_id: number;
  rule_name: string;
  status: string;
  severity: string;
  source: string;
  message: string;
  metric_value: string | null;
  channels_notified: string[];
  details: Record<string, unknown>;
  agent_id: string | null;
  timestamp: string;
}

interface AlertSummary {
  total_rules: number;
  active_rules: number;
  firing_count: number;
  last_24h: Record<string, number>;
}

/* ─── API alias ─── */
const alertsApi = api.alerts;

/* ─── Severity badge ─── */

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    critical: "bg-destructive/20 text-destructive border-destructive/30",
    warning: "bg-status-warning/20 text-status-warning border-status-warning/30",
    info: "bg-status-info/20 text-status-info border-status-info/30",
  };
  return (
    <span className={`px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border ${colors[severity] || colors.info}`}>
      {severity}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { color: string; icon: React.ReactNode }> = {
    firing: { color: "text-destructive", icon: <XCircle className="w-3 h-3" /> },
    resolved: { color: "text-status-healthy", icon: <CheckCircle2 className="w-3 h-3" /> },
    test: { color: "text-status-info", icon: <TestTube className="w-3 h-3" /> },
  };
  const c = config[status] || config.firing;
  return (
    <span className={`flex items-center gap-1 text-xs ${c.color}`}>
      {c.icon} {status}
    </span>
  );
}

/* ─── Create/Edit Rule Modal ─── */

const SOURCES = ["finops", "phi_shield", "health", "observatory", "custom"];
const OPERATORS = ["gt", "lt", "gte", "lte", "eq", "neq"];
const CHANNELS = ["webhook", "email", "teams"];
const SEVERITIES = ["info", "warning", "critical"];

const METRIC_PRESETS: Record<string, string[]> = {
  finops: ["budget_pct", "daily_cost_usd", "monthly_cost_usd"],
  phi_shield: ["phi_detected", "phi_count"],
  health: ["agent_health_failed", "error_rate", "latency_p95_ms"],
  observatory: ["error_rate", "latency_p95_ms", "total_cost_usd"],
  custom: [],
};

function RuleForm({
  rule,
  onSave,
  onCancel,
}: {
  rule?: AlertRule;
  onSave: (data: Partial<AlertRule>) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(rule?.name || "");
  const [description, setDescription] = useState(rule?.description || "");
  const [source, setSource] = useState(rule?.source || "finops");
  const [metric, setMetric] = useState(rule?.condition_metric || "budget_pct");
  const [operator, setOperator] = useState(rule?.condition_operator || "gt");
  const [value, setValue] = useState(rule?.condition_value || "80");
  const [channels, setChannels] = useState<string[]>(rule?.channels || []);
  const [severity, setSeverity] = useState(rule?.severity || "warning");
  const [cooldown, setCooldown] = useState(rule?.cooldown_minutes || 15);
  const [webhookUrl, setWebhookUrl] = useState(rule?.channel_config?.webhook_url || "");
  const [emailTo, setEmailTo] = useState(rule?.channel_config?.email_to || "");
  const [teamsUrl, setTeamsUrl] = useState(rule?.channel_config?.teams_webhook_url || "");
  const [agentFilter, setAgentFilter] = useState(rule?.agent_id_filter || "");

  const handleSubmit = () => {
    const channelConfig: Record<string, string> = {};
    if (webhookUrl) channelConfig.webhook_url = webhookUrl;
    if (emailTo) channelConfig.email_to = emailTo;
    if (teamsUrl) channelConfig.teams_webhook_url = teamsUrl;

    onSave({
      name,
      description,
      source,
      condition_type: "threshold",
      condition_metric: metric,
      condition_operator: operator,
      condition_value: value,
      channels,
      channel_config: channelConfig,
      severity,
      cooldown_minutes: cooldown,
      agent_id_filter: agentFilter || null,
    });
  };

  const inputClass = "w-full bg-muted/10 border border-border rounded px-3 py-1.5 text-sm text-foreground focus:outline-none focus:border-primary/50";
  const labelClass = "text-xs text-muted-foreground uppercase tracking-wider mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-background border border-border rounded-lg w-full max-w-lg max-h-[90vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground">
            {rule ? "Edit Alert Rule" : "New Alert Rule"}
          </h3>
          <button onClick={onCancel} className="text-muted-foreground hover:text-foreground/80">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className={labelClass}>Name</label>
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Budget > 80%" />
          </div>

          <div>
            <label className={labelClass}>Description</label>
            <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional description" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Source</label>
              <select className={inputClass} value={source} onChange={(e) => { setSource(e.target.value); setMetric(METRIC_PRESETS[e.target.value]?.[0] || ""); }}>
                {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Severity</label>
              <select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={labelClass}>Metric</label>
              <input className={inputClass} value={metric} onChange={(e) => setMetric(e.target.value)}
                list="metric-presets" placeholder="metric name" />
              <datalist id="metric-presets">
                {(METRIC_PRESETS[source] || []).map((m) => <option key={m} value={m} />)}
              </datalist>
            </div>
            <div>
              <label className={labelClass}>Operator</label>
              <select className={inputClass} value={operator} onChange={(e) => setOperator(e.target.value)}>
                {OPERATORS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>Value</label>
              <input className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} placeholder="80" />
            </div>
          </div>

          <div>
            <label className={labelClass}>Cooldown (minutes)</label>
            <input className={inputClass} type="number" value={cooldown} onChange={(e) => setCooldown(Number(e.target.value))} />
          </div>

          <div>
            <label className={labelClass}>Agent Filter (optional)</label>
            <input className={inputClass} value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} placeholder="e.g. sam-hr" />
          </div>

          <div>
            <label className={labelClass}>Channels</label>
            <div className="flex gap-3 mt-1">
              {CHANNELS.map((ch: string) => (
                <label key={ch} className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={channels.includes(ch)}
                    onChange={(e) =>
                      setChannels(e.target.checked ? [...channels, ch] : channels.filter((c) => c !== ch))
                    }
                    className="rounded border-border bg-muted/10"
                  />
                  {ch}
                </label>
              ))}
            </div>
          </div>

          {channels.includes("webhook") && (
            <div>
              <label className={labelClass}>Webhook URL</label>
              <input className={inputClass} value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://..." />
            </div>
          )}
          {channels.includes("email") && (
            <div>
              <label className={labelClass}>Email To</label>
              <input className={inputClass} value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="ops@hospital.org" />
            </div>
          )}
          {channels.includes("teams") && (
            <div>
              <label className={labelClass}>Teams Webhook URL</label>
              <input className={inputClass} value={teamsUrl} onChange={(e) => setTeamsUrl(e.target.value)} placeholder="https://outlook.office.com/webhook/..." />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={onCancel} className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground border border-border rounded">
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!name || !metric || !value}
              className="px-3 py-1.5 text-xs bg-primary hover:bg-primary/90 text-white rounded disabled:opacity-30"
            >
              {rule ? "Update" : "Create"} Rule
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export default function AlertsPage() {
  const [tab, setTab] = useState<"rules" | "history">("rules");
  const [showForm, setShowForm] = useState(false);
  const [editRule, setEditRule] = useState<AlertRule | undefined>();
  const [testResult, setTestResult] = useState<string | null>(null);

  const fetchRules = useCallback(() => alertsApi.rules(), []);
  const fetchHistory = useCallback(() => alertsApi.history(100), []);
  const fetchSummary = useCallback(() => alertsApi.summary(), []);

  const { data: rules, refresh: refreshRules } = useStablePolling(fetchRules, 10000);
  const { data: history, refresh: refreshHistory } = useStablePolling(fetchHistory, 10000);
  const { data: summary } = useStablePolling(fetchSummary, 10000);

  const handleCreate = async (data: Partial<AlertRule>) => {
    await alertsApi.createRule(data);
    setShowForm(false);
    refreshRules();
  };

  const handleUpdate = async (data: Partial<AlertRule>) => {
    if (editRule) {
      await alertsApi.updateRule(editRule.id, data);
      setEditRule(undefined);
      refreshRules();
    }
  };

  const handleDelete = async (id: number) => {
    await alertsApi.deleteRule(id);
    refreshRules();
  };

  const handleToggle = async (id: number) => {
    await alertsApi.toggleRule(id);
    refreshRules();
  };

  const handleTest = async (id: number) => {
    try {
      const result = await alertsApi.testRule(id);
      setTestResult(result.message);
      refreshHistory();
      setTimeout(() => setTestResult(null), 3000);
    } catch {
      setTestResult("Test failed");
      setTimeout(() => setTestResult(null), 3000);
    }
  };

  const s = summary || { total_rules: 0, active_rules: 0, firing_count: 0, last_24h: {} };

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Rules", value: s.total_rules, color: "text-foreground" },
          { label: "Active", value: s.active_rules, color: "text-primary" },
          { label: "Firing Now", value: s.firing_count, color: s.firing_count > 0 ? "text-destructive" : "text-status-healthy" },
          { label: "Last 24h", value: Object.values(s.last_24h).reduce((a: number, b) => a + (b as number), 0), color: "text-status-warning" },
        ].map((card) => (
          <div key={card.label} className="bg-muted/5 border border-border rounded-lg p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{card.label}</div>
            <div className={`text-2xl font-data font-bold ${card.color}`}>{card.value}</div>
          </div>
        ))}
      </div>

      {/* Tabs + actions */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {(["rules", "history"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-xs rounded ${tab === t ? "bg-muted/20 text-foreground" : "text-muted-foreground hover:text-foreground/80"}`}
            >
              {t === "rules" ? "Rules" : "History"}
            </button>
          ))}
        </div>
        {tab === "rules" && (
          <button
            onClick={() => { setEditRule(undefined); setShowForm(true); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary hover:bg-primary/90 text-white rounded"
          >
            <Plus className="w-3 h-3" /> New Rule
          </button>
        )}
      </div>

      {/* Test result toast */}
      {testResult && (
        <div className="bg-status-info/10 border border-status-info/20 rounded p-2 text-xs text-status-info">
          {testResult}
        </div>
      )}

      {/* Rules tab */}
      {tab === "rules" && (
        <div className="space-y-2">
          {!rules?.length && (
            <div className="text-center py-12 text-muted-foreground text-sm">
              No alert rules configured. Create one to get started.
            </div>
          )}
          {rules?.map((rule) => (
            <div key={rule.id} className="bg-muted/5 border border-border rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Bell className={`w-4 h-4 ${rule.active ? "text-primary" : "text-muted-foreground"}`} />
                  <div>
                    <div className="text-sm text-foreground font-medium">{rule.name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {rule.source} · {rule.condition_metric} {rule.condition_operator} {rule.condition_value}
                      {rule.agent_id_filter && ` · agent: ${rule.agent_id_filter}`}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={rule.severity} />
                  {rule.channels.map((ch: string) => (
                    <span key={ch} className="px-1.5 py-0.5 text-[9px] bg-muted/10 border border-border rounded text-muted-foreground">
                      {ch}
                    </span>
                  ))}
                  <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                    <Clock className="w-3 h-3" /> {rule.cooldown_minutes}m
                  </span>
                  <button onClick={() => handleToggle(rule.id)} className="text-muted-foreground hover:text-foreground/80" title="Toggle">
                    {rule.active ? <ToggleRight className="w-4 h-4 text-primary" /> : <ToggleLeft className="w-4 h-4" />}
                  </button>
                  <button onClick={() => handleTest(rule.id)} className="text-muted-foreground hover:text-primary" title="Test">
                    <Send className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => { setEditRule(rule); setShowForm(true); }} className="text-muted-foreground hover:text-foreground/80 text-xs">
                    Edit
                  </button>
                  <button onClick={() => handleDelete(rule.id)} className="text-muted-foreground hover:text-destructive" title="Delete">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              {rule.description && (
                <div className="mt-1 text-[11px] text-muted-foreground ml-7">{rule.description}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* History tab */}
      {tab === "history" && (
        <div className="space-y-1">
          {!history?.length && (
            <div className="text-center py-12 text-muted-foreground text-sm">
              No alert events yet.
            </div>
          )}
          {history?.map((event) => (
            <div key={event.id} className="bg-muted/5 border border-border rounded p-2.5 flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <StatusBadge status={event.status} />
                  <SeverityBadge severity={event.severity} />
                  <span className="text-xs text-muted-foreground font-medium truncate">{event.rule_name}</span>
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{event.message}</div>
                {event.agent_id && (
                  <span className="text-[10px] text-muted-foreground">agent: {event.agent_id}</span>
                )}
              </div>
              <div className="text-right shrink-0">
                <div className="text-[10px] text-muted-foreground">
                  {new Date(event.timestamp).toLocaleString()}
                </div>
                <div className="flex gap-1 mt-0.5 justify-end">
                  {event.channels_notified.map((ch: string) => (
                    <span key={ch} className="text-[9px] text-status-healthy">✓{ch}</span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <RuleForm
          rule={editRule}
          onSave={editRule ? handleUpdate : handleCreate}
          onCancel={() => { setShowForm(false); setEditRule(undefined); }}
        />
      )}
    </div>
  );
}
