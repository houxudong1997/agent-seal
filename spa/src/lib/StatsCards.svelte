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

  $effect(() => {
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  });
</script>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-icon events-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="4"/>
      </svg>
    </div>
    <div class="stat-body">
      <div class="stat-value events">{stats?.total_events ?? "--"}</div>
      <div class="stat-label">Total Events</div>
    </div>
  </div>

  <div class="stat-card">
    <div class="stat-icon sessions-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    </div>
    <div class="stat-body">
      <div class="stat-value sessions">{stats?.sessions ?? "--"}</div>
      <div class="stat-label">Sessions</div>
    </div>
  </div>

  <div class="stat-card">
    <div class="stat-icon integrity-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
    </div>
    <div class="stat-body">
      {#if stats}
        <div class="stat-value" class:integrity-ok={stats.integrity === "ok"} class:integrity-broken={stats.integrity === "broken"}>
          {stats.integrity === "ok" ? "Intact" : stats.integrity === "broken" ? "Broken" : "Unknown"}
        </div>
      {:else}
        <div class="stat-value">--</div>
      {/if}
      <div class="stat-label">Chain Integrity</div>
    </div>
  </div>

  <div class="stat-card">
    <div class="stat-icon types-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <polyline points="4 17 10 11 14 15 20 9"/><path d="M20 9h-6v6"/>
      </svg>
    </div>
    <div class="stat-body">
      <div class="stat-value types">{stats ? Object.keys(stats.event_types).length : "--"}</div>
      <div class="stat-label">Event Types</div>
    </div>
  </div>

  <div class="stat-card">
    <div class="stat-icon agents-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/>
        <circle cx="17" cy="7" r="4"/><path d="M21 21v-2a4 4 0 0 0-1.3-3"/>
      </svg>
    </div>
    <div class="stat-body">
      <div class="stat-value agents">{stats?.agents?.length ?? "--"}</div>
      <div class="stat-label">Agents</div>
    </div>
  </div>
</div>

{#if error}
  <div class="error-toast">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>
    </svg>
    Failed to load stats: {error}
  </div>
{/if}

<style>
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 22px;
    position: relative;
    z-index: 1;
  }

  .stat-card {
    display: flex;
    align-items: center;
    gap: 14px;
    background: var(--glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: 18px 20px;
    transition: all var(--transition);
  }

  .stat-card:hover {
    border-color: rgba(255, 255, 255, 0.08);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  }

  .stat-icon {
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius);
    flex-shrink: 0;
  }

  .events-icon {
    background: rgba(245, 158, 11, 0.1);
    color: var(--amber-text);
    box-shadow: 0 0 12px rgba(245, 158, 11, 0.05);
  }
  .sessions-icon {
    background: rgba(96, 165, 250, 0.1);
    color: var(--blue);
    box-shadow: 0 0 12px rgba(96, 165, 250, 0.05);
  }
  .integrity-icon {
    background: rgba(52, 211, 153, 0.1);
    color: var(--green);
    box-shadow: 0 0 12px rgba(52, 211, 153, 0.05);
  }
  .types-icon {
    background: rgba(167, 139, 250, 0.1);
    color: var(--purple);
    box-shadow: 0 0 12px rgba(167, 139, 250, 0.05);
  }
  .agents-icon {
    background: rgba(251, 191, 36, 0.1);
    color: #FBBF24;
    box-shadow: 0 0 12px rgba(251, 191, 36, 0.05);
  }

  .stat-body {
    min-width: 0;
  }

  .stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }

  .stat-value.events { color: var(--amber-text); }
  .stat-value.sessions { color: var(--blue); }
  .stat-value.types { color: var(--purple); }
  .stat-value.agents { color: #FBBF24; }
  .stat-value.integrity-ok { color: var(--green); }
  .stat-value.integrity-broken { color: var(--red); }

  .stat-label {
    font-size: 0.68rem;
    color: var(--dim);
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .error-toast {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(248, 113, 113, 0.06);
    border: 1px solid rgba(248, 113, 113, 0.15);
    color: var(--red);
    border-radius: var(--radius);
    padding: 8px 14px;
    margin-bottom: 16px;
    font-size: 0.78rem;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
  }

  @media (max-width: 640px) {
    .stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
