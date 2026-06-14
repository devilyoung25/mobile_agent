// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentThreadStreamProvider } from "./AgentThreadStreamProvider";

const mocks = vi.hoisted(() => ({
  continueQueuedMessages: vi.fn(),
  getQueuedMessages: vi.fn(),
  streamProps: undefined as { onCompleted?: () => void } | undefined,
}));

vi.mock("@langchain/langgraph-sdk", () => ({
  overrideFetchImplementation: vi.fn(),
}));

vi.mock("@langchain/react", () => ({
  StreamProvider: (props: { children: ReactNode; onCompleted?: () => void }) => {
    mocks.streamProps = props;
    return <>{props.children}</>;
  },
}));

vi.mock("./api", () => ({
  AgentsApiError: class AgentsApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  agentsApi: {
    continueQueuedMessages: mocks.continueQueuedMessages,
    getQueuedMessages: mocks.getQueuedMessages,
    langGraphApiUrl: "/dashboard/api",
  },
}));

function renderProvider(threadId: string | null = "thread-1") {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <AgentThreadStreamProvider threadId={threadId}>
        <div>child</div>
      </AgentThreadStreamProvider>
    </QueryClientProvider>,
  );
}

describe("AgentThreadStreamProvider queued continuation", () => {
  beforeEach(() => {
    mocks.continueQueuedMessages.mockReset();
    mocks.getQueuedMessages.mockReset();
    mocks.streamProps = undefined;
  });

  it("continues queued messages when the completed thread still has a queue", async () => {
    mocks.getQueuedMessages.mockResolvedValue({ count: 1, messages: [] });
    mocks.continueQueuedMessages.mockResolvedValue({
      status: "started",
      run_id: "run-1",
      queued: { count: 0, messages: [] },
    });

    renderProvider("thread-1");
    mocks.streamProps?.onCompleted?.();

    await waitFor(() => {
      expect(mocks.continueQueuedMessages).toHaveBeenCalledWith("thread-1");
    });
  });

  it("does not continue when the queue is empty", async () => {
    mocks.getQueuedMessages.mockResolvedValue({ count: 0, messages: [] });

    renderProvider("thread-1");
    mocks.streamProps?.onCompleted?.();

    await waitFor(() => {
      expect(mocks.getQueuedMessages).toHaveBeenCalledWith("thread-1");
    });
    expect(mocks.continueQueuedMessages).not.toHaveBeenCalled();
  });
});
