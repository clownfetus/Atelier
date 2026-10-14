// Optional catalogue updates never block setup, navigation or editing.
(() => {
  async function check(attempt = 0) {
    const label = document.getElementById('catalogue-status');
    try {
      const response = await fetch('/api/catalogue/status', { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error('Catalogue unavailable');
      const status = await response.json();
      label.textContent = status.updating ? (attempt < 80 ? 'Checking for new heroes and skins…' : 'Artwork refresh continues in the background. Saved portraits are available.')
        : status.error ? 'Offline · using saved portraits. Another check will run next launch.'
        : `${status.portraits} catalogue entries with artwork · checked at launch`;
      // A bounded status poll, not an asset refresh: avoid disturbing an open editor.
      if (status.updating && attempt < 80) setTimeout(() => check(attempt + 1), 3000);
    } catch {
      label.textContent = 'Using saved portraits. Another check will run next launch.';
    }
  }
  document.addEventListener('DOMContentLoaded', () => check());
})();
