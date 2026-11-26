(() => {
  const button = document.getElementById('launch-game');
  const label = document.getElementById('launch-game-label');
  const labels = {
    checking: ['Launch game', 'Checking whether Marvel Rivals is running'],
    unknown: ['Launch game', 'Could not check whether Marvel Rivals is running'],
    ready: ['Launch game', 'Launch Marvel Rivals through Steam'],
    starting: ['Starting…', 'Waiting for Marvel Rivals to start'],
    running: ['Game running', 'Marvel Rivals is running'],
  };
  let api;
  let poll;
  let request = 0;

  function show(state) {
    if (button.dataset.state === state) return;
    const [text, title] = labels[state];
    if (label.textContent !== text) label.textContent = text;
    button.title = title;
    button.setAttribute('aria-disabled', String(state !== 'ready'));
    button.dataset.state = state;
  }

  async function refresh(launch = false) {
    clearTimeout(poll);
    const current = ++request;
    if (launch) show('starting');
    let result;
    try {
      result = await (launch ? api.launch_game() : api.game_status());
    } catch {
      result = {state: 'unknown', error: 'Could not launch Marvel Rivals.'};
    }
    // A launch click can overtake a pending status poll.
    if (current !== request) return;
    show(result.state);
    if (launch && result.error) toast(result.error, 'error');
    poll = setTimeout(refresh, 2500);
  }

  function connect() {
    const bridge = window.pywebview?.api;
    if (api || !bridge?.game_status || !bridge.launch_game) return;
    api = bridge;
    show('checking');
    refresh();
  }

  button.addEventListener('click', () => {
    if (button.dataset.state === 'ready') refresh(true);
  });
  window.addEventListener('pywebviewready', connect);
  connect();
})();
