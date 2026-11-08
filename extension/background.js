// Clicking the toolbar button injects the overlay into the current tab.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['content.js'] });
  } catch (e) {
    console.error('mimikara: could not inject', e);
  }
});
