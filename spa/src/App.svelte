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

  // SSE stream connection
  const eventSource = createEventStream(
    (event) => {
      liveEvents = [...liveEvents.slice(-99), event]; // Keep last 100 events max
    },
    (status) => {
      streamStatus = status;
    },
  );

  // Clean up on unmount
  $effect(() => {
    return () => eventSource.close();
  });

  const tabs: { id: Tab; label: string }[] = [
    { id: "events", label: "Live Events" },
    { id: "sessions", label: "Sessions" },
    { id: "compliance", label: "Compliance" },
  ];
</script>

<div class="app-container">
  <!-- Header -->
  <header>
    <div>
      <h1><span class="logo-dot"></span>Agent Audit Dashboard</h1>
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
        {tab.label}
      </button>
    {/each}
  </div>

  <!-- Tab panels -->
  {#if activeTab === "events"}
    <EventList liveEvents={liveEvents} />
  {:else if activeTab === "sessions"}
    <SessionList />
  {:else if activeTab === "compliance"}
    <ComplianceView />
  {/if}
</div>

<style>
  :global(:root) {
    --bg: #0a0e14;
    --bg-secondary: #0f1721;
    --card: #111620;
    --card-hover: #161d2c;
    --border: #1e293b;
    --border-light: #2a3548;
    --text: #c9d1d9;
    --text-bright: #e6edf3;
    --dim: #6b7280;
    --green: #2ea043;
    --red: #da3633;
    --amber: #d29922;
    --cyan: #39d2c0;
    --blue: #58a6ff;
    --purple: #a371f7;
    --radius: 8px;
    --transition: 0.15s ease;
  }

  :global(*),
  :global(*::before),
  :global(*::after) {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    min-height: 100vh;
  }

  .app-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px 20px;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
    flex-wrap: wrap;
    gap: 12px;
  }

  header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--cyan);
    letter-spacing: -0.02em;
  }

  .logo-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--cyan);
    margin-right: 8px;
    box-shadow: 0 0 10px var(--cyan);
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .version-tag {
    font-size: 0.7rem;
    color: var(--dim);
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
  }

  .tabs {
    display: flex;
    gap: 0;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }

  .tab-btn {
    padding: 10px 20px;
    background: none;
    border: none;
    color: var(--dim);
    font-size: 0.85rem;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: all var(--transition);
    font-family: inherit;
  }

  .tab-btn:hover {
    color: var(--text);
  }

  .tab-btn.active {
    color: var(--cyan);
    border-bottom-color: var(--cyan);
  }

  @media (max-width: 640px) {
    .app-container {
      padding: 16px 12px;
    }
    header {
      flex-direction: column;
      align-items: flex-start;
    }
  }
</style>
