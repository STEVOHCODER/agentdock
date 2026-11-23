const BASE = "https://agentdock.link";
export async function get(path) {
  const response = await fetch(BASE + path);
  if (!response.ok) throw new Error('AgentDock request failed (' + response.status + ')');
  return response.json();
}
export async function search(query) {
  return get('/api/v1/skills/search?q=' + encodeURIComponent(query));
}
