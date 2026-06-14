import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useStreamContext as useAgentThreadStream } from "@langchain/react";

import type { SendAgentMessageVariables } from "@/lib/agents/queries";
import { AgentsApiError, agentsApi } from "@/lib/agents/api";
import { agentThreadKeys } from "@/lib/agents/queries";
import type { ImageChunk } from "@/lib/agents/types";

/**
 * Construct the message content for the LangGraph run.
 *
 * @param vars - The variables for the message.
 * @returns The message content.
 */
function messageContent(vars: SendAgentMessageVariables) {
  const text = vars.content.trim();
  const imageBlocks = vars.images?.map((image) => ({
    type: "image",
    base64: image.base64,
    mime_type: image.mimeType,
    ...(image.fileName ? { file_name: image.fileName } : {}),
  })) ?? [];
  return [...imageBlocks, ...(text ? [{ type: "text", text }] : [])];
}

/**
 * User-initiated sends from the prompt bar. Prefer this over calling `stream.submit`
 * directly so cache updates and the busy-thread queue path stay consistent.
 *
 * When the thread is idle, submits a new run via the stream commands endpoint.
 * When a run is already in flight (`stream.isLoading`), posts to the dashboard
 * `/messages` endpoint instead of using LangGraph `multitaskStrategy: "enqueue"`.
 * That endpoint writes to the thread store. Normal queued messages wait for
 * run completion; the prompt bar's explicit "Dirigir" action marks one queued
 * message for injection before the next model call.
 * 
 * @param threadId - The ID of the thread to submit the message to.
 * @returns The mutation object.
 */
export function useSubmitAgentMessage(threadId: string) {
  const queryClient = useQueryClient();
  const stream = useAgentThreadStream();

  return useMutation({
    mutationFn: async (vars: SendAgentMessageVariables) => {
      const queuedMessage = {
        content: vars.content,
        images: vars.images ?? ([] as Array<ImageChunk>),
      };
      const queue = () =>
        agentsApi.queueMessage(threadId, {
          content: vars.content,
          images: vars.images,
          model_id: vars.model_id,
          effort: vars.effort,
        });

      if (stream.isLoading) {
        await queue();
        return { queued: true, message: queuedMessage };
      }

      try {
        await queue();
        return { queued: true, message: queuedMessage };
      } catch (error) {
        if (!(error instanceof AgentsApiError) || error.status !== 409) {
          throw error;
        }
      }

      const config = (!vars.model_id || !vars.effort)
        ? undefined
        : {
          configurable: {
            agent_model_id: vars.model_id,
            agent_effort: vars.effort,
          },
        };

      await stream.submit(
        { messages: [{ type: "human", content: messageContent(vars) }] },
        { config },
      );
      return { queued: false, message: queuedMessage };
    },
    onSuccess: () => {
      queryClient.setQueryData(agentThreadKeys.detail(threadId), (prev) =>
        prev ? { ...prev, status: "running" as const } : prev,
      );
      void queryClient.invalidateQueries({ queryKey: agentThreadKeys.all, exact: true });
    },
  });
}
