// Trivial / control-flow handlers.

export function handleSpec(): Record<string, unknown> {
  // PROVISOIRE: désactivé — passe direct à call_agent_schema
  return {
    status: 'success',
    pcb_status: 'INITIAL',
    note: 'Spec skipped — proceed directly to call_agent_schema.',
  };
}

export function handleAskUser(input: Record<string, unknown>): Record<string, unknown> {
  return {
    status: 'waiting',
    question: input['question'],
    note: 'En attente de réponse utilisateur.',
  };
}
