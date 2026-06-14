// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSubmitAgentMessage } from "./useSubmitAgentMessage";

const mocks = vi.hoisted(() => {
  class AgentsApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }

  return {
    AgentsApiError,
    isLoading: false,
    queueMessage: vi.fn(),
    submit: vi.fn(),
  };
});

vi.mock("@langchain/react", () => ({
  useStreamContext: () => ({
    isLoading: mocks.isLoading,
    submit: mocks.submit,
  }),
}));

vi.mock("@/lib/agents/api", () => ({
  AgentsApiError: mocks.AgentsApiError,
  agentsApi: {
    queueMessage: mocks.queueMessage,
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

describe("useSubmitAgentMessage", () => {
  beforeEach(() => {
    mocks.isLoading = false;
    mocks.queueMessage.mockReset();
    mocks.submit.mockReset();
  });

  it("queues and returns the queued message while the stream is busy", async () => {
    mocks.isLoading = true;
    mocks.queueMessage.mockResolvedValue({});
    const { result } = renderHook(() => useSubmitAgentMessage("thread-1"), { wrapper });

    const response = await result.current.mutateAsync({
      content: "seguimiento",
      images: [],
      model_id: null,
      effort: null,
    });

    expect(mocks.queueMessage).toHaveBeenCalledWith("thread-1", {
      content: "seguimiento",
      images: [],
      model_id: null,
      effort: null,
    });
    expect(mocks.submit).not.toHaveBeenCalled();
    expect(response).toEqual({
      queued: true,
      message: { content: "seguimiento", images: [] },
    });
  });

  it("falls back to stream.submit when the thread is idle", async () => {
    mocks.queueMessage.mockRejectedValue(new mocks.AgentsApiError(409, "thread idle"));
    mocks.submit.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSubmitAgentMessage("thread-1"), { wrapper });

    const response = await result.current.mutateAsync({
      content: "primer mensaje",
      images: [],
      model_id: "on-auto-coder",
      effort: "medium",
    });

    expect(mocks.submit).toHaveBeenCalledWith(
      { messages: [{ type: "human", content: [{ type: "text", text: "primer mensaje" }] }] },
      {
        config: {
          configurable: {
            agent_model_id: "on-auto-coder",
            agent_effort: "medium",
          },
        },
      },
    );
    expect(response).toEqual({
      queued: false,
      message: { content: "primer mensaje", images: [] },
    });
  });
});
