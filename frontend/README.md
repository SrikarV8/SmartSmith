# SmartSmith Frontend

A UI for the StartSmith agentic business assistant, built with
**Create React App + TypeScript + Tailwind CSS**.

The backend (`../runtime_loop.py`) currently runs in the terminal. This
frontend is wired to a **mock API** (`src/api/mockApi.ts`) that simulates the
RAG pipeline's behavior (vector_only / hybrid / google_only) so you can
develop the UI without a server. Replace `sendChatMessage` with a real
`fetch` call once you wrap `runtime_loop.py` in FastAPI.

## Features

- Dark theme
- Left sidebar with chat history (persisted in `localStorage`)
- Collapsible sidebar
- Streaming-style token-by-token rendering with stop button
- Retrieval-mode badge on assistant messages (internal / web / hybrid)
- Right-side **Sources panel** showing vector + web citations for each assistant message
- Empty-state suggestion chips
- Fully responsive composer with auto-growing textarea and Enter-to-send (Shift+Enter = newline)

## Quick start

```bash
cd frontend
npm install
npm start
```

App runs at http://localhost:3000.

## Project structure

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── api/
│   │   └── mockApi.ts        # Simulates runtime_loop.py responses
│   ├── components/
│   │   ├── ChatInput.tsx
│   │   ├── ChatView.tsx
│   │   ├── CitationsPanel.tsx
│   │   ├── MessageBubble.tsx
│   │   └── Sidebar.tsx
│   ├── hooks/
│   │   └── useLocalStorage.ts
│   ├── types/
│   │   └── chat.ts
│   ├── App.tsx
│   ├── index.css             # Tailwind + custom scrollbar/animations
│   └── index.tsx
├── package.json
├── postcss.config.js
├── tailwind.config.js
└── tsconfig.json
```

## Wiring it to the real backend later

In `src/api/mockApi.ts`, replace `sendChatMessage` with something like:

```ts
export async function sendChatMessage(
  query: string,
  onToken: (t: string) => void,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const res = await fetch("http://localhost:8000/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  const data = await res.json();
  onToken(data.answer); // or stream via SSE / ReadableStream
  return {
    answer: data.answer,
    sourceMode: data.source_mode,
    citations: data.citations,
  };
}
```

On the Python side, wrap the functions from `runtime_loop.py` in a FastAPI
endpoint that returns `{ answer, source_mode, citations }`.
