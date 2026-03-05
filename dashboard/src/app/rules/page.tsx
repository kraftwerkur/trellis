"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Rule, Agent } from "@/types/trellis";

function conditionToEnglish(conditions: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(conditions)) {
    if (typeof value === "string") {
      parts.push(`${key} = "${value}"`);
    } else if (typeof value === "object" && value !== null) {
      const inner = value as Record<string, unknown>;
      for (const [op, val] of Object.entries(inner)) {
        if (op === "$contains" || op === "contains") parts.push(`${key} contains "${val}"`);
        else if (op === "$regex" || op === "regex") parts.push(`${key} matches /${val}/`);
        else if (op === "$in" || op === "in") parts.push(`${key} in [${(val as string[]).join(", ")}]`);
        else parts.push(`${key} ${op} ${JSON.stringify(val)}`);
      }
    } else {
      parts.push(`${key} = ${JSON.stringify(value)}`);
    }
  }
  return parts.join(" AND ") || "all envelopes";
}

function targetToString(actions: Rule["actions"], agentMap: Record<string, string>): string {
  const targets = Array.isArray(actions.route_to) ? actions.route_to : [actions.route_to];
  return targets.map(t => agentMap[t] ?? t.slice(0, 12)).join(", ");
}

type RuleFormData = {
  name: string;
  priority: number;
  conditions: string;
  route_to: string[];
  set_priority: string;
  fan_out: boolean;
  active: boolean;
};

const emptyForm: RuleFormData = {
  name: "",
  priority: 100,
  conditions: "{}",
  route_to: [],
  set_priority: "",
  fan_out: false,
  active: true,
};

function ruleToForm(r: Rule): RuleFormData {
  const routeTo = Array.isArray(r.actions.route_to) ? r.actions.route_to : [r.actions.route_to];
  return {
    name: r.name,
    priority: r.priority,
    conditions: JSON.stringify(r.conditions, null, 2),
    route_to: routeTo,
    set_priority: r.actions.set_priority ?? "",
    fan_out: r.fan_out,
    active: r.active,
  };
}

function RuleModal({
  form,
  setForm,
  agents,
  onSave,
  onCancel,
  saving,
  title,
}: {
  form: RuleFormData;
  setForm: (f: RuleFormData) => void;
  agents: Agent[];
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  title: string;
}) {
  const [condError, setCondError] = useState("");

  const validateConditions = (v: string) => {
    try { JSON.parse(v); setCondError(""); } catch { setCondError("Invalid JSON"); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="card-dark w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="px-4 py-3 border-b border-white/[0.06]">
          <span className="text-sm font-medium text-zinc-200">{title}</span>
        </div>
        <div className="p-4 space-y-4">
          {/* Name */}
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-1">Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-3 py-2 text-sm text-zinc-200 outline-none focus:border-cyan-500/50"
              placeholder="Rule name"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-1">Priority</label>
            <input
              type="number"
              value={form.priority}
              onChange={e => setForm({ ...form, priority: parseInt(e.target.value) || 0 })}
              className="w-24 bg-white/[0.04] border border-white/[0.08] rounded px-3 py-2 text-sm text-zinc-200 outline-none focus:border-cyan-500/50"
            />
            <span className="text-xs text-zinc-600 ml-2">Lower = higher priority</span>
          </div>

          {/* Conditions */}
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-1">Conditions (JSON)</label>
            <textarea
              value={form.conditions}
              onChange={e => { setForm({ ...form, conditions: e.target.value }); validateConditions(e.target.value); }}
              rows={4}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-3 py-2 text-sm text-zinc-200 font-mono outline-none focus:border-cyan-500/50"
              placeholder='{"source_type": "email"}'
            />
            {condError && <span className="text-xs text-red-400">{condError}</span>}
          </div>

          {/* Route To */}
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-1">Route To (agents)</label>
            <div className="space-y-1.5 max-h-36 overflow-y-auto">
              {agents.map(a => (
                <label key={a.agent_id} className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer hover:text-zinc-100">
                  <input
                    type="checkbox"
                    checked={form.route_to.includes(a.agent_id)}
                    onChange={e => {
                      const next = e.target.checked
                        ? [...form.route_to, a.agent_id]
                        : form.route_to.filter(id => id !== a.agent_id);
                      setForm({ ...form, route_to: next });
                    }}
                    className="accent-cyan-500"
                  />
                  {a.name}
                </label>
              ))}
              {!agents.length && <span className="text-xs text-zinc-600">No agents found</span>}
            </div>
          </div>

          {/* Set Priority */}
          <div>
            <label className="text-xs text-zinc-500 uppercase tracking-wider block mb-1">Set Priority (optional)</label>
            <input
              type="text"
              value={form.set_priority}
              onChange={e => setForm({ ...form, set_priority: e.target.value })}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-3 py-2 text-sm text-zinc-200 outline-none focus:border-cyan-500/50"
              placeholder="e.g. high, low, urgent"
            />
          </div>

          {/* Toggles */}
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <button
                type="button"
                onClick={() => setForm({ ...form, fan_out: !form.fan_out })}
                className={`w-8 h-4 rounded-full relative transition-colors ${form.fan_out ? "bg-amber-500/30" : "bg-zinc-800"}`}
              >
                <div className={`w-3 h-3 rounded-full absolute top-0.5 transition-all ${form.fan_out ? "left-4 bg-amber-400" : "left-0.5 bg-zinc-600"}`} />
              </button>
              Fan-out
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <button
                type="button"
                onClick={() => setForm({ ...form, active: !form.active })}
                className={`w-8 h-4 rounded-full relative transition-colors ${form.active ? "bg-emerald-500/20" : "bg-zinc-800"}`}
              >
                <div className={`w-3 h-3 rounded-full absolute top-0.5 transition-all ${form.active ? "left-4 bg-emerald-500" : "left-0.5 bg-zinc-600"}`} />
              </button>
              Active
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="px-4 py-3 border-t border-white/[0.06] flex justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors">
            Cancel
          </button>
          <button
            onClick={onSave}
            disabled={saving || !form.name || !form.route_to.length || !!condError}
            className="px-3 py-1.5 text-xs bg-cyan-500/20 text-cyan-400 rounded hover:bg-cyan-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function RulesPage() {
  const fetchRules = useCallback(() => api.rules.list(), []);
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const { data: rules, loading, refresh } = useStablePolling<Rule[]>(fetchRules, 10000);
  const { data: agents } = useStablePolling<Agent[]>(fetchAgents, 30000);

  const [modal, setModal] = useState<"create" | "edit" | null>(null);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [form, setForm] = useState<RuleFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  const agentMap = useMemo(() => {
    const m: Record<string, string> = {};
    (agents ?? []).forEach(a => { m[a.agent_id] = a.name; });
    return m;
  }, [agents]);

  const sorted = useMemo(() => (rules ?? []).sort((a, b) => a.priority - b.priority), [rules]);

  const openCreate = () => {
    setForm(emptyForm);
    setEditingRule(null);
    setModal("create");
  };

  const openEdit = (r: Rule) => {
    setForm(ruleToForm(r));
    setEditingRule(r);
    setModal("edit");
  };

  const closeModal = () => {
    setModal(null);
    setEditingRule(null);
  };

  const buildPayload = () => {
    let conditions: Record<string, unknown>;
    try { conditions = JSON.parse(form.conditions); } catch { return null; }
    const actions: Rule["actions"] = {
      route_to: form.route_to.length === 1 ? form.route_to[0] : form.route_to,
    };
    if (form.set_priority) actions.set_priority = form.set_priority;
    return {
      name: form.name,
      priority: form.priority,
      conditions,
      actions,
      active: form.active,
      fan_out: form.fan_out,
    };
  };

  const handleSave = async () => {
    const payload = buildPayload();
    if (!payload) return;
    setSaving(true);
    try {
      if (modal === "edit" && editingRule) {
        await api.rules.update(editingRule.id, payload);
      } else {
        await api.rules.create(payload);
      }
      closeModal();
      refresh();
    } catch (e) {
      console.error("Save failed:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.rules.delete(id);
      setDeleteConfirm(null);
      refresh();
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  const handleToggle = async (r: Rule) => {
    try {
      await api.rules.update(r.id, { active: !r.active });
      refresh();
    } catch (e) {
      console.error("Toggle failed:", e);
    }
  };

  return (
    <>
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
          <div>
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Routing Rules</span>
            {rules && <span className="text-xs text-zinc-600 ml-2">({rules.length})</span>}
          </div>
          <button
            onClick={openCreate}
            className="px-2.5 py-1 text-xs bg-emerald-500/15 text-emerald-400 rounded hover:bg-emerald-500/25 transition-colors"
          >
            + Add Rule
          </button>
        </div>
        <div className="divide-y divide-white/[0.04]">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="px-4 py-3"><div className="skeleton h-10 w-full" /></div>
            ))
          ) : !sorted.length ? (
            <div className="text-center text-zinc-600 py-8 text-sm">No rules configured</div>
          ) : (
            sorted.map(r => (
              <div key={r.id} className="px-4 py-3 table-row-hover group">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-3 cursor-pointer flex-1" onClick={() => openEdit(r)}>
                    <span className="font-data text-[10px] text-zinc-600 bg-white/[0.04] px-1.5 py-0.5 rounded">P{r.priority}</span>
                    <span className="text-sm font-medium text-zinc-200">{r.name}</span>
                    {r.fan_out && <span className="text-[10px] text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">fan-out</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    {deleteConfirm === r.id ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-red-400">Delete?</span>
                        <button onClick={() => handleDelete(r.id)} className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors">
                          Yes
                        </button>
                        <button onClick={() => setDeleteConfirm(null)} className="px-2 py-0.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirm(r.id)}
                        className="px-2 py-0.5 text-xs text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                      >
                        Delete
                      </button>
                    )}
                    <button
                      onClick={() => handleToggle(r)}
                      className={`w-8 h-4 rounded-full relative transition-colors ${r.active ? "bg-emerald-500/20" : "bg-zinc-800"}`}
                    >
                      <div className={`w-3 h-3 rounded-full absolute top-0.5 transition-all ${r.active ? "left-4 bg-emerald-500" : "left-0.5 bg-zinc-600"}`} />
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs cursor-pointer" onClick={() => openEdit(r)}>
                  <span className="text-zinc-400">when</span>
                  <span className="font-data text-cyan-400/70">{conditionToEnglish(r.conditions)}</span>
                  <span className="flow-arrow" />
                  <span className="text-zinc-400">route to</span>
                  <span className="font-data text-purple-400/80">{targetToString(r.actions, agentMap)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {modal && (
        <RuleModal
          form={form}
          setForm={setForm}
          agents={agents ?? []}
          onSave={handleSave}
          onCancel={closeModal}
          saving={saving}
          title={modal === "create" ? "Create Rule" : `Edit Rule: ${editingRule?.name ?? ""}`}
        />
      )}
    </>
  );
}
