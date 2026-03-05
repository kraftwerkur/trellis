(globalThis.TURBOPACK||(globalThis.TURBOPACK=[])).push(["object"==typeof document?document.currentScript:void 0,23657,e=>{"use strict";var t=e.i(85366),s=e.i(32983);let a=(0,s.default)("terminal",[["path",{d:"M12 19h8",key:"baeox8"}],["path",{d:"m4 17 6-6-6-6",key:"1yngyt"}]]),n=(0,s.default)("external-link",[["path",{d:"M15 3h6v6",key:"1q9fwt"}],["path",{d:"M10 14 21 3",key:"gplh6r"}],["path",{d:"M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",key:"a6xqqp"}]]);function i({children:e}){return(0,t.jsx)("pre",{className:"bg-black/40 border border-white/[0.06] rounded p-3 text-[11px] font-data text-zinc-300 overflow-x-auto whitespace-pre",children:e})}function l({title:e,children:s}){return(0,t.jsxs)("div",{className:"card-dark p-4 space-y-3",children:[(0,t.jsx)("h2",{className:"text-sm font-semibold text-zinc-200",children:e}),s]})}function r(){return(0,t.jsxs)("div",{className:"space-y-3 max-w-3xl",children:[(0,t.jsx)(l,{title:"What is Trellis?",children:(0,t.jsx)("p",{className:"text-xs text-zinc-400 leading-relaxed",children:"Trellis is an agent orchestration platform that routes incoming events to the right AI agents using configurable rules. It provides a unified gateway for managing multiple agents, tracking costs, and monitoring event flow in real time."})}),(0,t.jsx)(l,{title:"Architecture",children:(0,t.jsx)("pre",{className:"text-[11px] font-data text-cyan-400/80 leading-relaxed",children:`  Sources          Intake            Router              Agents
  ──────          ──────            ──────              ──────
  Email   ─┐
  Webhook  ├──▶  HTTP Adapter ──▶  Trellis Router ──▶  Agent A
  API      ├──▶   /api/adapter      │                   Agent B
  Slack   ─┘       /http            │  Rules Engine     Agent C
                                    │  (priority-based)
                                    └──▶ Fan-out (multi-agent)`})}),(0,t.jsx)(l,{title:"Quick Start",children:(0,t.jsxs)("div",{className:"space-y-4",children:[(0,t.jsxs)("div",{children:[(0,t.jsxs)("h3",{className:"text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5",children:[(0,t.jsx)(a,{className:"w-3 h-3 text-cyan-400"})," 1. Register an Agent"]}),(0,t.jsx)(i,{children:`curl -X POST http://localhost:8000/api/agents \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "my-agent",
    "agent_type": "llm",
    "department": "operations",
    "endpoint_url": "http://localhost:9000/handle",
    "framework": "langchain",
    "maturity": "beta"
  }'`})]}),(0,t.jsxs)("div",{children:[(0,t.jsxs)("h3",{className:"text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5",children:[(0,t.jsx)(a,{className:"w-3 h-3 text-emerald-400"})," 2. Create a Routing Rule"]}),(0,t.jsx)(i,{children:`curl -X POST http://localhost:8000/api/rules \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "route-emails",
    "priority": 10,
    "conditions": { "source_type": "email" },
    "actions": { "route_to": "my-agent" },
    "active": true
  }'`})]}),(0,t.jsxs)("div",{children:[(0,t.jsxs)("h3",{className:"text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5",children:[(0,t.jsx)(a,{className:"w-3 h-3 text-purple-400"})," 3. Submit an Event"]}),(0,t.jsx)(i,{children:`curl -X POST http://localhost:8000/api/adapter/http \\
  -H "Content-Type: application/json" \\
  -d '{
    "source_type": "email",
    "payload": {
      "from": "user@example.com",
      "subject": "Help request",
      "body": "I need assistance with..."
    }
  }'`})]})]})}),(0,t.jsx)(l,{title:"Key Concepts",children:(0,t.jsxs)("dl",{className:"space-y-2 text-xs",children:[(0,t.jsxs)("div",{children:[(0,t.jsx)("dt",{className:"font-semibold text-zinc-300",children:"Envelopes"}),(0,t.jsx)("dd",{className:"text-zinc-500",children:"The standard wrapper around every inbound event. Contains source type, payload, and routing metadata."})]}),(0,t.jsxs)("div",{children:[(0,t.jsx)("dt",{className:"font-semibold text-zinc-300",children:"Routing Rules"}),(0,t.jsx)("dd",{className:"text-zinc-500",children:"Condition-action pairs evaluated in priority order. The first matching rule determines which agent handles the event."})]}),(0,t.jsxs)("div",{children:[(0,t.jsx)("dt",{className:"font-semibold text-zinc-300",children:"Fan-out"}),(0,t.jsx)("dd",{className:"text-zinc-500",children:"A rule can route a single event to multiple agents simultaneously for parallel processing."})]}),(0,t.jsxs)("div",{children:[(0,t.jsx)("dt",{className:"font-semibold text-zinc-300",children:"Agents"}),(0,t.jsx)("dd",{className:"text-zinc-500",children:"Registered AI services (LLM-based or otherwise) that receive and process routed events via their endpoint URL."})]}),(0,t.jsxs)("div",{children:[(0,t.jsx)("dt",{className:"font-semibold text-zinc-300",children:"Gateway"}),(0,t.jsx)("dd",{className:"text-zinc-500",children:"The central Trellis service that handles intake, routing, agent health checks, and cost tracking."})]})]})}),(0,t.jsx)(l,{title:"API Reference",children:(0,t.jsxs)("p",{className:"text-xs text-zinc-400",children:["Full interactive API documentation is available at"," ",(0,t.jsxs)("a",{href:"/docs",className:"text-cyan-400 hover:underline inline-flex items-center gap-1",children:["/docs (Swagger) ",(0,t.jsx)(n,{className:"w-3 h-3"})]})," ","on the Trellis server."]})})]})}e.s(["default",()=>r],23657)}]);