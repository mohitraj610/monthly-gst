import { useEffect, useRef, useState } from "react";
import { ArrowRight, MessageCircle, Send, X } from "lucide-react";
import { answerGuide, guideStep } from "./guidance";
import type { GuideAction, GuideContext } from "./guidance";

export function GuidePanel({
  context,
  onAction,
  onClose,
}: {
  context: GuideContext;
  onAction?: (action: GuideAction) => void;
  onClose?: () => void;
}) {
  const [input, setInput] = useState("");
  const messagesRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<
    { question: string; answer: string }[]
  >([]);
  const step = guideStep(context);
  useEffect(() => {
    if (messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);
  function ask(question: string) {
    if (!question.trim()) return;
    setMessages((previous) => [
      ...previous.slice(-7),
      { question: question.trim(), answer: answerGuide(question, context) },
    ]);
    setInput("");
  }
  const questions = context.row
    ? ["Which record is correct?", "Why two copies?", "What should I do next?"]
    : context.phase === "export"
      ? ["What is in the export?", "Can I claim ITC?", "What should I do next?"]
      : context.phase
        ? [
            "Which columns do I need?",
            "What is row granularity?",
            "What is GSTR-2B?",
          ]
        : ["What are my books?", "What is GSTR-2B?", "What should I do next?"];
  return (
    <section className="guide-panel" aria-label="Monthly guide">
      <div className="guide-heading">
        <MessageCircle size={18} />
        <strong>Monthly guide</strong>
        <span>Offline</span>
        {onClose && (
          <button
            type="button"
            className="icon-button"
            aria-label="Close guide"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        )}
      </div>
      <div className="guide-step">
        <small>{step.title}</small>
        <p>{step.text}</p>
        {step.action && onAction && (
          <button
            type="button"
            className="button primary"
            onClick={() => onAction(step.action!)}
          >
            {step.button}
            <ArrowRight size={15} />
          </button>
        )}
      </div>
      <div
        className="guide-messages"
        ref={messagesRef}
        aria-live="polite"
        aria-relevant="additions"
      >
        {messages.map((message, i) => (
          <div className="guide-exchange" key={i}>
            <p className="guide-question">{message.question}</p>
            <p className="guide-answer">{message.answer}</p>
          </div>
        ))}
      </div>
      <div className="guide-questions">
        {questions.map((q) => (
          <button type="button" key={q} onClick={() => ask(q)}>
            {q}
          </button>
        ))}
      </div>
      <form
        className="guide-input"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <input
          aria-label="Ask the guide"
          placeholder="Ask about this screen…"
          maxLength={500}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          type="submit"
          aria-label="Send question"
          disabled={!input.trim()}
        >
          <Send size={16} />
        </button>
      </form>
      <small className="guide-footnote">
        Prepared guidance using this screen. No cloud AI. No edits to your
        books.
      </small>
    </section>
  );
}
