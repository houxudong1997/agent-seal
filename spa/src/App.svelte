<script lang="ts">
  import StatsCards from "./lib/StatsCards.svelte";
  import EventList from "./lib/EventList.svelte";
  import SessionList from "./lib/SessionList.svelte";
  import ComplianceView from "./lib/ComplianceView.svelte";
  import StreamIndicator from "./lib/StreamIndicator.svelte";
  import { createEventStream, type EventRecord } from "./lib/api";

  type Tab = "events" | "sessions" | "compliance";

  let activeTab: Tab = $state("events");
  let liveEvents: EventRecord[] = $state([]);
  let streamStatus: "connecting" | "connected" | "reconnecting" | "disconnected" = $state("connecting");

  const eventSource = createEventStream(
    (event) => {
      liveEvents = [...liveEvents.slice(-99), event];
    },
    (status) => {
      streamStatus = status;
    },
  );

  $effect(() => {
    return () => eventSource.close();
  });

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: "events", label: "Live Events", icon: "⚡" },
    { id: "sessions", label: "Sessions", icon: "◆" },
    { id: "compliance", label: "Compliance", icon: "◈" },
  ];
</script>

<div class="app-container">
  <!-- Background ambient -->
  <div class="ambient-bg"></div>
  <div class="ambient-glow"></div>

  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">
        <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
          <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
          <circle cx="12" cy="12" r="4" fill="#F59E0B" opacity="0.8"/>
          <circle cx="12" cy="12" r="2" fill="#FBBF24"/>
          <path d="M2 12h20" stroke="currentColor" stroke-width="0.5" opacity="0.1"/>
          <path d="M12 2v20" stroke="currentColor" stroke-width="0.5" opacity="0.1"/>
        </svg>
      </div>
      <div class="brand-text">
        <h1>Agent Seal</h1>
        <span class="brand-sub">Dashboard</span>
      </div>
    </div>
    <div class="header-right">
      <span class="version-tag">v1.0.0</span>
      <StreamIndicator status={streamStatus} />
    </div>
  </header>

  <!-- Stats cards -->
  <StatsCards />

  <!-- Tab navigation -->
  <div class="tabs" role="tablist">
    {#each tabs as tab}
      <button
        class="tab-btn"
        class:active={activeTab === tab.id}
        role="tab"
        aria-selected={activeTab === tab.id}
        onclick={() => (activeTab = tab.id)}
      >
        <span class="tab-icon">{tab.icon}</span>
        <span>{tab.label}</span>
        {#if activeTab === tab.id}
          <span class="tab-indicator"></span>
        {/if}
      </button>
    {/each}
  </div>

  <!-- Tab panels -->
  <div class="tab-panel" class:visible={activeTab === "events"} role="tabpanel">
    {#if activeTab === "events"}
      <EventList liveEvents={liveEvents} />
    {/if}
  </div>
  <div class="tab-panel" class:visible={activeTab === "sessions"} role="tabpanel">
    {#if activeTab === "sessions"}
      <SessionList />
    {/if}
  </div>
  <div class="tab-panel" class:visible={activeTab === "compliance"} role="tabpanel">
    {#if activeTab === "compliance"}
      <ComplianceView />
    {/if}
  </div>
</div>

<style>
  :global(:root) {
    font-size: 18px;
    --bg: #07080a;
    --bg-gradient: radial-gradient(ellipse at 50% 0%, #0f111a 0%, #07080a 100%);
    --glass: rgba(16, 17, 25, 0.65);
    --glass-alt: rgba(22, 24, 35, 0.45);
    --glass-border: rgba(255, 255, 255, 0.04);
    --glass-border-active: rgba(245, 158, 11, 0.25);
    --glass-hover: rgba(255, 255, 255, 0.04);
    --glass-blur: blur(28px);
    --text: #d4d7dd;
    --text-bright: #eaedf2;
    --dim: #5f6570;
    --amber: #F59E0B;
    --amber-soft: rgba(245, 158, 11, 0.1);
    --amber-glow: rgba(245, 158, 11, 0.18);
    --amber-text: #FBBF24;
    --green: #34d399;
    --green-soft: rgba(52, 211, 153, 0.12);
    --red: #f87171;
    --red-soft: rgba(248, 113, 113, 0.12);
    --blue: #60a5fa;
    --blue-soft: rgba(96, 165, 250, 0.12);
    --purple: #a78bfa;
    --purple-soft: rgba(167, 139, 250, 0.12);
    --radius: 10px;
    --radius-sm: 6px;
    --radius-lg: 14px;
    --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    --font: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", sans-serif;
    --font-mono: "SF Mono", "Fira Code", "JetBrains Mono", monospace;
  }

  :global(*),
  :global(*::before),
  :global(*::after) {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  :global(body) {
    font-family: var(--font);
    background: var(--bg);
    background-image: var(--bg-gradient);
    color: var(--text);
    line-height: 1.5;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  :global(::-webkit-scrollbar) {
    width: 6px;
    height: 6px;
  }
  :global(::-webkit-scrollbar-track) {
    background: transparent;
  }
  :global(::-webkit-scrollbar-thumb) {
    background: rgba(255, 255, 255, 0.06);
    border-radius: 3px;
  }
  :global(::-webkit-scrollbar-thumb:hover) {
    background: rgba(255, 255, 255, 0.1);
  }

  .app-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 30px 28px;
    position: relative;
  }

  .ambient-bg {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    background:
      radial-gradient(ellipse 600px 400px at 20% 10%, rgba(245, 158, 11, 0.015) 0%, transparent 100%),
      radial-gradient(ellipse 500px 500px at 80% 20%, rgba(245, 158, 11, 0.008) 0%, transparent 100%);
    z-index: 0;
  }

  .ambient-glow {
    position: fixed;
    top: -40%;
    left: 50%;
    transform: translateX(-50%);
    width: 800px;
    height: 500px;
    pointer-events: none;
    background: radial-gradient(ellipse, rgba(245, 158, 11, 0.02) 0%, transparent 70%);
    z-index: 0;
    opacity: 0.6;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 22px;
    flex-wrap: wrap;
    gap: 12px;
    position: relative;
    z-index: 1;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .brand-icon {
    color: var(--amber);
    filter: drop-shadow(0 0 12px rgba(245, 158, 11, 0.35));
  }

  .brand-text {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  header h1 {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--text-bright);
    letter-spacing: -0.03em;
    line-height: 1;
    background: linear-gradient(135deg, var(--text-bright) 60%, var(--amber-text));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .brand-sub {
    font-size: 0.75rem;
    color: var(--dim);
    font-weight: 500;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .version-tag {
    font-size: 0.65rem;
    color: var(--dim);
    background: var(--glass);
    border: 1px solid var(--glass-border);
    border-radius: 4px;
    padding: 3px 8px;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
  }

  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 22px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 4px;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    position: relative;
    z-index: 1;
  }

  .tab-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 20px;
    background: none;
    border: none;
    color: var(--dim);
    font-size: 0.82rem;
    font-weight: 500;
    cursor: pointer;
    border-radius: var(--radius);
    transition: all var(--transition);
    font-family: var(--font);
    position: relative;
  }

  .tab-btn:hover {
    color: var(--text);
    background: rgba(255, 255, 255, 0.03);
  }

  .tab-btn.active {
    color: var(--amber-text);
    background: rgba(245, 158, 11, 0.08);
  }

  .tab-icon {
    font-size: 0.85rem;
    opacity: 0.7;
  }

  .tab-btn.active .tab-icon {
    opacity: 1;
  }

  .tab-indicator {
    position: absolute;
    bottom: -1px;
    left: 50%;
    transform: translateX(-50%);
    width: 16px;
    height: 2px;
    background: var(--amber);
    border-radius: 1px;
    box-shadow: 0 0 8px var(--amber), 0 0 16px rgba(245, 158, 11, 0.3);
  }

  .tab-panel {
    display: none;
    position: relative;
    z-index: 1;
  }
  .tab-panel.visible {
    display: block;
    animation: fadeIn 0.25s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 640px) {
    .app-container {
      padding: 16px 12px;
    }
    header {
      flex-direction: column;
      align-items: flex-start;
    }
    .tabs {
      width: 100%;
    }
    .tab-btn {
      flex: 1;
      justify-content: center;
      padding: 9px 12px;
      font-size: 0.75rem;
    }
  }
</style>
