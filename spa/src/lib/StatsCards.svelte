<script lang="ts">
  import { fetchStats, type StatsResponse } from "./api";

  let stats: StatsResponse | null = $state(null);
  let error: string | null = $state(null);

  async function load() {
    try {
      stats = await fetchStats();
      error = null;
    } catch (e) {
      error = String(e);
    }
  }

  // Load on mount and refresh every 15s
  $effect(() => {
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  });
</script>

<div class="stats-grid">
  <div class="stat-card">
    <div class="value events">{stats?.total_events ?? "--"}</div>
    <div class="label">Total Events</div>
  </div>

  <div class="stat-card">
    <div class="value sessions">{stats?.sessions ?? "--"}</div>
    <div class="label">Sessions</div>
  </div>

  <div class="stat-card">
    {#if stats}
      <div class="value" class:integrity={stats.integrity === "ok"} class:broken={stats.integrity === "broken"}>
        {stats.integrity === "ok" ? "✓ Intact" : stats.integrity === "broken" ? "✗ Broken" : "? Unknown"}
      </div>
    {:else}
      <div class="value integrity">--</div>
    {/if}
    <div class="label">Chain Integrity</div>
  </div>

  <div class="stat-card">
    <div class="value types">{stats ? Object.keys(stats.event_types).length : "--"}</div>
    <div class="label">Event Types</div>
  </div>

  <div class="stat-card">
    <div class="value agents">{stats?.agents?.length ?? "--"}</div>
    <div class="label">Agents</div>
  </div>
</div>

{#if error}
  <div class="error-toast">Failed to load stats: {error}</div>
{/if}

<style>
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }

  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 18px;
    transition: border-color var(--transition);
  }

  .stat-card:hover {
    border-color: var(--border-light);
  }

  .value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.1;
  }

  .value.events {
    color: var(--cyan);
  }

  .value.sessions {
    color: var(--blue);
  }

  .value.integrity {
    color: var(--green);
  }

  .value.broken {
    color: var(--red);
  }

  .value.types {
    color: var(--amber);
  }

  .value.agents {
    color: var(--purple);
  }

  .label {
    font-size: 0.75rem;
    color: var(--dim);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .error-toast {
    background: rgba(218, 54, 51, 0.15);
    border: 1px solid var(--red);
    color: var(--red);
    border-radius: var(--radius);
    padding: 8px 14px;
    margin-bottom: 16px;
    font-size: 0.82rem;
  }

  @media (max-width: 640px) {
    .stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
