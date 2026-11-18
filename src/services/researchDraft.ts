const draftKey = 'hive_agent_prompt';
const previousDraftKey = 'synq_agent_prompt';

export function readResearchDraft(): string | null {
  try {
    const current = localStorage.getItem(draftKey);
    if (current !== null) return current;
    const previous = localStorage.getItem(previousDraftKey);
    if (previous !== null) saveResearchDraft(previous);
    return previous;
  } catch {
    return null;
  }
}

export function saveResearchDraft(draft: string): void {
  try {
    localStorage.setItem(draftKey, draft);
  } catch {
    // Research still works when browser storage is unavailable.
  }
}
