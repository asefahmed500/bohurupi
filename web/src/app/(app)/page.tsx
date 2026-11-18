import { ChatView } from "@/components/chat/chat-view";

// Documented instant opt-out (Next 16 Cache Components): the chat route is a
// realtime, auth-gated view. Its instant shell is the AppShell loading
// skeleton rendered by the (app) layout; the conversation stream itself only
// exists after the client auth check + WebSocket connect, so segment-level
// instant validation is not meaningful here. The production build prerenders
// this route (verified: `next build` -> ○ /).
export const instant = false;

export default function ChatPage() {
  return <ChatView />;
}
