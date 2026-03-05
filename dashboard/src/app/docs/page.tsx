"use client";

import { BookOpen, Terminal, ExternalLink } from "lucide-react";

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="bg-black/40 border border-white/[0.06] rounded p-3 text-[11px] font-data text-zinc-300 overflow-x-auto whitespace-pre">
      {children}
    </pre>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card-dark p-4 space-y-3">
      <h2 className="text-sm font-semibold text-zinc-200">{title}</h2>
      {children}
    </div>
  );
}

export default function DocsPage() {
  return (
    <div className="space-y-3 max-w-3xl">
      <Section title="What is Trellis?">
        <p className="text-xs text-zinc-400 leading-relaxed">
          Trellis is an agent orchestration platform that routes incoming events to the right AI agents using configurable rules.
          It provides a unified gateway for managing multiple agents, tracking costs, and monitoring event flow in real time.
        </p>
      </Section>

      <Section title="Architecture">
        <pre className="text-[11px] font-data text-cyan-400/80 leading-relaxed">
{`  Sources          Intake            Router              Agents
  ──────          ──────            ──────              ──────
  Email   ─┐
  Webhook  ├──▶  HTTP Adapter ──▶  Trellis Router ──▶  Agent A
  API      ├──▶   /api/adapter      │                   Agent B
  Slack   ─┘       /http            │  Rules Engine     Agent C
                                    │  (priority-based)
                                    └──▶ Fan-out (multi-agent)`}
        </pre>
      </Section>

      <Section title="Quick Start">
        <div className="space-y-4">
          <div>
            <h3 className="text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
              <Terminal className="w-3 h-3 text-cyan-400" /> 1. Register an Agent
            </h3>
            <CodeBlock>{`curl -X POST http://localhost:8000/api/agents \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "my-agent",
    "agent_type": "llm",
    "department": "operations",
    "endpoint_url": "http://localhost:9000/handle",
    "framework": "langchain",
    "maturity": "beta"
  }'`}</CodeBlock>
          </div>

          <div>
            <h3 className="text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
              <Terminal className="w-3 h-3 text-emerald-400" /> 2. Create a Routing Rule
            </h3>
            <CodeBlock>{`curl -X POST http://localhost:8000/api/rules \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "route-emails",
    "priority": 10,
    "conditions": { "source_type": "email" },
    "actions": { "route_to": "my-agent" },
    "active": true
  }'`}</CodeBlock>
          </div>

          <div>
            <h3 className="text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
              <Terminal className="w-3 h-3 text-purple-400" /> 3. Submit an Event
            </h3>
            <CodeBlock>{`curl -X POST http://localhost:8000/api/adapter/http \\
  -H "Content-Type: application/json" \\
  -d '{
    "source_type": "email",
    "payload": {
      "from": "user@example.com",
      "subject": "Help request",
      "body": "I need assistance with..."
    }
  }'`}</CodeBlock>
          </div>
        </div>
      </Section>

      <Section title="Key Concepts">
        <dl className="space-y-2 text-xs">
          <div>
            <dt className="font-semibold text-zinc-300">Envelopes</dt>
            <dd className="text-zinc-500">The standard wrapper around every inbound event. Contains source type, payload, and routing metadata.</dd>
          </div>
          <div>
            <dt className="font-semibold text-zinc-300">Routing Rules</dt>
            <dd className="text-zinc-500">Condition-action pairs evaluated in priority order. The first matching rule determines which agent handles the event.</dd>
          </div>
          <div>
            <dt className="font-semibold text-zinc-300">Fan-out</dt>
            <dd className="text-zinc-500">A rule can route a single event to multiple agents simultaneously for parallel processing.</dd>
          </div>
          <div>
            <dt className="font-semibold text-zinc-300">Agents</dt>
            <dd className="text-zinc-500">Registered AI services (LLM-based or otherwise) that receive and process routed events via their endpoint URL.</dd>
          </div>
          <div>
            <dt className="font-semibold text-zinc-300">Gateway</dt>
            <dd className="text-zinc-500">The central Trellis service that handles intake, routing, agent health checks, and cost tracking.</dd>
          </div>
        </dl>
      </Section>

      <Section title="API Reference">
        <p className="text-xs text-zinc-400">
          Full interactive API documentation is available at{" "}
          <a href="/docs" className="text-cyan-400 hover:underline inline-flex items-center gap-1">
            /docs (Swagger) <ExternalLink className="w-3 h-3" />
          </a>
          {" "}on the Trellis server.
        </p>
      </Section>
    </div>
  );
}
