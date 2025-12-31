"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

type Msg = { id: number; role: string; content: string };

export default function ChatPage() {
  const [history, setHistory] = useState<Msg[]>([]);
  const [message, setMessage] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);

  const router = useRouter();

  async function load() {
    setErr(null);
    try {
      const data = await api("/chat/history");
      setHistory(data);
    } catch (e: any) {
      setErr(e.message ?? "Failed to load chat history");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function clearHistory() {
    setErr(null);
    try {
      await api("/chat/clear", { method: "DELETE" });
      setHistory([]);
    } catch (e: any) {
      setErr(e.message ?? "Failed to clear chat history");
    }
  }

  async function send() {
    const trimmed = message.trim();
    if (!trimmed) return;

    setErr(null);

    const localUser: Msg = { id: Date.now(), role: "user", content: trimmed };
    setHistory((h) => [...h, localUser]);
    setMessage("");

    // show assistant working indicator
    setIsTyping(true);

    try {
      const data = await api("/chat/message", {
        method: "POST",
        body: JSON.stringify({ message: localUser.content }),
      });

      setIsTyping(false);

      setHistory((h) => [
        ...h,
        { id: Date.now() + 1, role: "assistant", content: data.message },
      ]);
    } catch (e: any) {
      setIsTyping(false);
      setErr(e.message ?? "Failed to send message");

      // IMPORTANT: if backend saved reply but fetch failed, reload history
      load();
    }
  }

  return (
    <main className="min-h-screen bg-gray-100 flex justify-center p-4 sm:p-6">
      <div className="w-full max-w-2xl bg-white rounded-xl shadow-md flex flex-col min-h-[calc(100vh-2rem)] sm:min-h-0">
        {/* Header */}
        <div className="flex items-start sm:items-center justify-between gap-3 px-4 py-3 border-b">
          <h2 className="text-base sm:text-lg font-semibold">🤖 Chatbot</h2>

          <div className="flex flex-wrap justify-end gap-2">
            <button
              onClick={clearHistory}
              className="text-sm px-3 py-1 rounded-md bg-red-100 hover:bg-red-200 text-red-700"
            >
              Clear
            </button>
            <button
              onClick={() => router.push("/dashboard")}
              className="text-sm px-3 py-1 rounded-md bg-gray-200 hover:bg-gray-300"
            >
              Back
            </button>
          </div>
        </div>

        {err && (
          <p className="px-4 py-2 text-sm text-red-600 bg-red-50 break-words">
            {err}
          </p>
        )}

        {/* Chat */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-3">
          {history.map((m) => (
            <div
              key={m.id}
              className={`rounded-lg px-3 py-2 text-sm break-words ${
                m.role === "user"
                  ? "ml-auto bg-blue-500 text-white max-w-[90%] sm:max-w-[80%]"
                  : "mr-auto bg-gray-200 text-gray-900 max-w-[90%] sm:max-w-[80%]"
              }`}
            >
              <span className="block font-semibold mb-1 capitalize">
                {m.role}
              </span>

              {m.content.split("\n").map((line, idx) => (
                <p key={idx} className="whitespace-pre-wrap">
                  {line}
                </p>
              ))}
            </div>
          ))}

          {/* Assistant working indicator */}
          {isTyping && (
            <div className="mr-auto max-w-[90%] sm:max-w-[80%] rounded-lg bg-gray-200 px-3 py-2 text-sm text-gray-700 animate-pulse break-words">
              <span className="block font-semibold mb-1 capitalize">
                assistant
              </span>
              Assistant is working…
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t p-3 flex flex-col sm:flex-row gap-2">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder='Type: Add todo title is Buy milk and description is 12 kg milk'
            className="w-full sm:flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            onKeyDown={(e) => {
              if (e.key === "Enter") send();
            }}
          />
          <button
            onClick={send}
            className="w-full sm:w-auto px-4 py-2 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700"
          >
            Send
          </button>
        </div>

        {/* Examples */}
        <p className="px-4 py-2 text-xs text-gray-500 break-words">
          Examples: “Show my todos”, “Add todo title is Buy milk and description
          is 12kg milk”, “Update 2 title is Buy orange”, “Change description of 1
          to 20kg milk”, “Complete 3”, “Delete 2”
        </p>
      </div>
    </main>
  );
}
