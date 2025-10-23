import React, { useRef, useState } from "react";
import Logo from "components/Logo.jsx";
import Composer from "components/Composer.jsx";
import ProfileForm from "components/ProfileForm.jsx";
import TherapySummaryCard from "components/TherapySummaryCard.jsx";
import CitationsCard from "components/CitationsCard.jsx";

const API = {
  chat: "/api/chat",
  meal: "/api/meal-plan",
  upload: "/api/upload",
};

function parseList(s) {
  if (!s) return [];
  return String(s).split(",").map(x => x.trim()).filter(Boolean);
}

function Message({ m, answerMeta }) {
  return (
    <div
      className={
        "max-w-[85%] rounded-xl p-3 " +
        (m.role === "user" ? "bg-white/5 border border-white/10" : "bg-emerald-500/10 border border-emerald-400/20 ml-auto")
      }
    >
      <div className="whitespace-pre-wrap text-sm">{m.text}</div>
      {m.role !== "user" && answerMeta?.model_used && (
        <div className="mt-2 text-[11px] text-slate-400">
          Model: <span className="text-pink-300">{answerMeta.model_used}</span>
          {answerMeta.llm_model_id ? ` (${answerMeta.llm_model_id})` : ""}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([
    { role: "user", text: "I have eczema and I'm on metformin. What should I eat more of?" }
  ]);
  const [answerMeta, setAnswerMeta] = useState({ model_used: null, llm_model_id: null });
  const [profile, setProfile] = useState({
    age: "", sex: "", weight_kg: "", height_cm: "",
    country: "", diagnosis: "", allergies: "", medications: ""
  });
  const [consent, setConsent] = useState(false);
  const [week, setWeek] = useState(false);
  const [therapy, setTherapy] = useState(null);
  const [therapySummary, setTherapySummary] = useState("");
  const [citations, setCitations] = useState([]);
  const [sources, setSources] = useState([]);
  const [disclaimer, setDisclaimer] = useState("");
  const [fileText, setFileText] = useState("");
  const fileRef = useRef();

  async function handleUpload(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    const res = await fetch(API.upload, { method: "POST", body: form });
    const data = await res.json();
    setFileText(data.extracted_text || "");
    setMessages(m => [...m, { role: "assistant", text: File "${data.file_name}" uploaded. Extracted ${(data.extracted_text || "").length} chars. }]);
  }

  async function sendChat(query) {
    const payload = {
      query,
      file_text: fileText || "",
      profile: {
        age: profile.age ? Number(profile.age) : undefined,
        sex: profile.sex || undefined,
        weight_kg: profile.weight_kg ? Number(profile.weight_kg) : undefined,
        height_cm: profile.height_cm ? Number(profile.height_cm) : undefined,
        country: profile.country || undefined,
        diagnosis: profile.diagnosis || undefined,
        allergies: parseList(profile.allergies),
        medications: parseList(profile.medications),
      },
    };

    const res = await fetch(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.error) {
      setMessages(m => [...m, { role: "assistant", text: ⚠ ${data.error}: ${data.detail || ""} }]);
      return;
    }

    setMessages(m => [...m, { role: "assistant", text: data.answer || "(No answer)" }]);
    setTherapy(data.therapy_output || null);
    setTherapySummary(data.therapy_summary || "");
    setSources(data.sources || []);
    setAnswerMeta({ model_used: data.model_used, llm_model_id: data.llm_model_id });
    setDisclaimer(data.disclaimer || "");
  }

  async function getMealPlan() {
    const payload = {
      query: "staple foods",
      consent_meal_plan: consent,
      duration_days: week ? 7 : 1,
      profile: {
        age: profile.age ? Number(profile.age) : undefined,
        sex: profile.sex || undefined,
        weight_kg: profile.weight_kg ? Number(profile.weight_kg) : undefined,
        height_cm: profile.height_cm ? Number(profile.height_cm) : undefined,
        country: profile.country || undefined,
        diagnosis: profile.diagnosis || undefined,
        allergies: parseList(profile.allergies),
        medications: parseList(profile.medications),
      }
    };

    const res = await fetch(API.meal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.error) {
      setMessages(m => [...m, { role: "assistant", text: ⚠ ${data.error}${data.missing ? " — missing: " + data.missing.join(", ") : ""} }]);
      return;
    }

    setTherapy(data.therapy_output || null);
    setTherapySummary(data.therapy_summary || "");
    setCitations(data.citations || []);
    setSources(data.sources || []);
    setDisclaimer(data.disclaimer || "");

    if (data.weekly_plan) {
      setMessages(m => [...m, { role: "assistant", text: Generated a ${data.weekly_plan.length}-day plan. See the Therapy Summary and Citations. }]);
    } else {
      setMessages(m => [...m, { role: "assistant", text: "Generated a 1-day plan. See the Therapy Summary and Citations." }]);
    }
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-10 glass border-b border-white/10 bg-slate-950/40">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-3">
          <Logo />
          <div>
            <h1 className="text-white font-semibold tracking-tight">NutriIntel</h1>
            <p className="text-[12px] text-slate-400 leading-tight">Precision nutrition, simplified.</p>
          </div>
          <div className="ml-auto text-xs text-slate-400">
            Always educational—not medical advice.
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="mx-auto max-w-7xl px-4 py-8 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Chat area */}
        <section className="lg:col-span-7 space-y-4">
          {/* Chat stream */}
          <div className="rounded-2xl border border-white/10 bg-slate-900/40 glass p-4">
            <h3 className="text-slate-200 font-medium mb-2">Chat</h3>
            <div className="space-y-3 text-sm">
              {messages.map((m, i) => <Message key={i} m={m} answerMeta={answerMeta} />)}
            </div>

            {/* Composer */}
            <div className="mt-4 grid gap-3">
              {/* File upload */}
              <div className="flex items-center gap-3">
                <input ref={fileRef} type="file" className="hidden" onChange={handleUpload} />
                <button
                  onClick={() => fileRef.current?.click()}
                  className="px-3 py-2 text-sm rounded-lg bg-white/10 hover:bg-white/15 border border-white/10"
                >
                  Upload file
                </button>
                <div className="text-xs text-slate-400">Attach PDFs/TXT with labs or notes. We’ll parse and add as context.</div>
              </div>

              {/* Query row */}
              <Composer onSend={(q) => {
                if (!q.trim()) return;
                setMessages(m => [...m, { role: "user", text: q }]);
                sendChat(q);
              }} />
            </div>
          </div>

          {/* Explain & Plan */}
          <div className="rounded-2xl border border-white/10 bg-slate-900/40 glass p-4">
            <h3 className="text-slate-200 font-medium mb-3">Explain & Plan</h3>
            <p className="text-sm text-slate-300 mb-3">
              The assistant will explain your query’s category (e.g., therapy, dermatology, recommendation) and summarize the plan.
              It will <span className="text-pink-300 font-medium">not</span> assume age/weight/height for BMI—please provide them
              below or upload a file with your details. If you don’t know your weight/height, we’ll plan using age group defaults.
            </p>

            {/* Profile form */}
            <ProfileForm profile={profile} setProfile={setProfile} />

            {/* Planning consent */}
            <div className="mt-4 flex flex-wrap items-center gap-4">
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-pink-500" checked={consent} onChange={e => setConsent(e.target.checked)} />
                I consent to generate a tailored meal plan.
              </label>
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-pink-500" checked={week} onChange={e => setWeek(e.target.checked)} />
                Generate one-week plan
              </label>
              <button
                onClick={getMealPlan}
                className="ml-auto px-4 py-2 rounded-lg bg-pink-500 hover:bg-pink-600 text-white text-sm font-medium"
              >
                Generate {week ? "7-day" : "1-day"} plan
              </button>
            </div>

            {disclaimer && (
              <p className="mt-3 text-[12px] text-slate-400">
                {disclaimer}
              </p>
            )}
          </div>
        </section>

        {/* Right side: Summary + Citations */}
        <aside className="lg:col-span-5 space-y-4">
          <TherapySummaryCard
            slots={{
              age: profile.age || undefined,
              sex: profile.sex || undefined,
              diagnosis: profile.diagnosis || undefined,
              allergies: parseList(profile.allergies),
              medications: parseList(profile.medications)
            }}
            therapyOutput={therapy}
          />

          <CitationsCard citations={citations} sources={sources} />
        </aside>
      </main>

      {/* Footer */}
      <footer className="py-6 text-center text-xs text-slate-500">
        © {new Date().getFullYear()} NutriIntel — Precision nutrition, simplified.
      </footer>
    </div>
  );
}