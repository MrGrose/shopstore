import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SupportSection } from "./SupportSection";

vi.mock("../../../lib/storefront/api", () => {
  class StorefrontApiError extends Error {
    userMessage: string;
    status: number;

    constructor(userMessage: string, status: number) {
      super(userMessage);
      this.name = "StorefrontApiError";
      this.userMessage = userMessage;
      this.status = status;
    }
  }

  return {
    StorefrontApiError,
    storefrontApiFetch: vi.fn(),
    storefrontApiFetchBlob: vi.fn(),
  };
});

import { StorefrontApiError, storefrontApiFetch, storefrontApiFetchBlob } from "../../../lib/storefront/api";

const mockFetch = vi.mocked(storefrontApiFetch);
const mockBlobFetch = vi.mocked(storefrontApiFetchBlob);

const ticketList = [
  {
    id: 1,
    topic: "general",
    topic_label: "Общий вопрос",
    status: "waiting_staff",
    order_id: null,
    created_at: "2026-07-04T10:00:00",
    updated_at: "2026-07-04T10:00:00",
    last_message_preview: "Первое сообщение",
  },
  {
    id: 2,
    topic: "order_question",
    topic_label: "Вопрос по заказу",
    status: "waiting_customer",
    order_id: 55,
    created_at: "2026-07-03T10:00:00",
    updated_at: "2026-07-04T11:00:00",
    last_message_preview: "Ответ поддержки",
  },
];

const linkableOrders = [
  {
    id: 55,
    status: "processing",
    total_amount: "3000.00",
    created_at: "2026-07-01T10:00:00",
  },
];

const ticketDetailOpen = {
  ...ticketList[0],
  closed_at: null,
  messages: [
    {
      id: 10,
      author_type: "customer" as const,
      body: "Первое сообщение",
      created_at: "2026-07-04T10:00:00",
    },
  ],
};

const ticketDetailClosed = {
  ...ticketList[1],
  status: "closed",
  closed_at: "2026-07-04T12:00:00",
  messages: [
    {
      id: 11,
      author_type: "customer" as const,
      body: "Вопрос",
      created_at: "2026-07-04T10:00:00",
    },
    {
      id: 12,
      author_type: "staff" as const,
      body: "Ответ",
      created_at: "2026-07-04T11:00:00",
    },
  ],
};

function listPage(items: typeof ticketList) {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 20,
    total_pages: 1,
  };
}

function mockInitialLoad() {
  mockFetch.mockImplementation(async (path: string) => {
    if (path.startsWith("/support/tickets?")) return listPage(ticketList);
    if (path === "/support/linkable-orders") return linkableOrders;
    throw new Error(`unexpected path ${path}`);
  });
}

describe("SupportSection", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockInitialLoad();
    let preview = 0;
    URL.createObjectURL = vi.fn(() => `blob:preview-${++preview}`);
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders support tab content with topic options and optional order select", async () => {
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Поддержка" })).toBeTruthy();
    expect(screen.getByText("Тема")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Вопрос по заказу" })).toBeTruthy();
    expect(screen.getByText("Заказ (необязательно)")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Без привязки к заказу" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "#55 · 3000.00 ₽ · processing" })).toBeTruthy();
  });

  it("shows ticket list with russian statuses", async () => {
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Ожидает ответа")).toBeTruthy();
    const ticket2 = await screen.findByRole("button", { name: /#2 · Вопрос по заказу/ });
    expect(ticket2.textContent).toContain("Ответ получен");
    expect(screen.getByText("#1 · Общий вопрос")).toBeTruthy();
  });

  it("creates ticket without order", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets" && init?.method === "POST") {
        return { ...ticketDetailOpen, id: 3 };
      }
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      if (path === "/support/tickets/3") return { ...ticketDetailOpen, id: 3 };
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    await screen.findByText("Мои обращения");
    await user.type(screen.getByPlaceholderText("Опишите вопрос или проблему"), "Новый вопрос");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/support/tickets",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            topic: "order_question",
            body: "Новый вопрос",
            order_id: null,
          }),
        }),
      );
    });
  });

  it("creates ticket with selected order", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets" && init?.method === "POST") {
        return { ...ticketDetailOpen, id: 4, order_id: 55 };
      }
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      if (path === "/support/tickets/4") {
        return { ...ticketDetailOpen, id: 4, order_id: 55 };
      }
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    await screen.findByText("Заказ (необязательно)");
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[1], "55");
    await user.type(screen.getByPlaceholderText("Опишите вопрос или проблему"), "По заказу");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/support/tickets",
        expect.objectContaining({
          body: JSON.stringify({
            topic: "order_question",
            body: "По заказу",
            order_id: 55,
          }),
        }),
      );
    });
  });

  it("loads conversation history and sends reply", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets/1") return ticketDetailOpen;
      if (path === "/support/tickets/1/messages" && init?.method === "POST") {
        return {
          ...ticketDetailOpen,
          status: "waiting_staff",
          messages: [
            ...ticketDetailOpen.messages,
            {
              id: 13,
              author_type: "customer",
              body: "Дополнение",
              created_at: "2026-07-04T10:05:00",
            },
          ],
        };
      }
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: /#1 · Общий вопрос/ }));
    expect((await screen.findAllByText("Первое сообщение")).length).toBeGreaterThan(0);

    await user.type(screen.getByPlaceholderText("Новое сообщение"), "Дополнение");
    const replyForm = screen.getByPlaceholderText("Новое сообщение").closest("form");
    if (!replyForm) throw new Error("reply form not found");
    await user.click(within(replyForm).getByRole("button", { name: "Отправить" }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/support/tickets/1/messages",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("closes open ticket and blocks reply form for closed ticket", async () => {
    const user = userEvent.setup();
    const openTicket2 = { ...ticketDetailOpen, id: 2, topic_label: "Вопрос по заказу" };
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets/2") return openTicket2;
      if (path === "/support/tickets/2/close" && init?.method === "POST") {
        return ticketDetailClosed;
      }
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: /#2 · Вопрос по заказу/ }));
    await user.click(screen.getByRole("button", { name: "Закрыть обращение" }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/support/tickets/2/close",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(
      await screen.findByText("Обращение закрыто. Чтобы задать новый вопрос — создайте новое обращение выше."),
    ).toBeTruthy();
    expect(screen.queryByPlaceholderText("Новое сообщение")).toBeNull();
  });

  it("shows api error message", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/support/tickets?")) {
        throw new StorefrontApiError("Не удалось загрузить", 500);
      }
      if (path === "/support/linkable-orders") return [];
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Не удалось загрузить");
  });

  it("shows plus picker caption and rejects an 11th photo", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );
    await screen.findByText("Мои обращения");
    expect(screen.getAllByRole("button", { name: /Добавить фото/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("0/10").length).toBeGreaterThan(0);
    const input = screen.getAllByLabelText("Прикрепить фото")[0];
    expect(input).toHaveProperty("multiple", true);
    const batch = Array.from(
      { length: 10 },
      (_, i) => new File([new Uint8Array([1])], `shot-${i}.jpg`, { type: "image/jpeg" }),
    );
    await user.upload(input, batch);
    expect(screen.getAllByRole("button", { name: /Удалить фото/ }).length).toBe(10);
    await user.upload(
      input,
      new File([new Uint8Array([1])], "shot-10.jpg", { type: "image/jpeg" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Можно прикрепить не больше 10 фото.",
    );
    expect(screen.getAllByRole("button", { name: /Удалить фото/ }).length).toBe(10);
  });

  it("removes a selected photo before send", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );
    await screen.findByText("Мои обращения");
    const input = screen.getAllByLabelText("Прикрепить фото")[0];
    await user.upload(input, [
      new File([new Uint8Array([1])], "a.jpg", { type: "image/jpeg" }),
      new File([new Uint8Array([1])], "b.jpg", { type: "image/jpeg" }),
    ]);
    expect(screen.getByRole("img", { name: "Фото 1" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Фото 2" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Удалить фото 1" }));
    expect(screen.queryByRole("img", { name: "Фото 2" })).toBeNull();
    expect(screen.getByRole("img", { name: "Фото 1" })).toBeTruthy();
  });

  it("sends FormData when photos are attached", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets" && init?.method === "POST") {
        return { ...ticketDetailOpen, id: 9 };
      }
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      if (path === "/support/tickets/9") return { ...ticketDetailOpen, id: 9 };
      throw new Error(`unexpected ${path}`);
    });

    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );

    await screen.findByText("Мои обращения");
    const file = new File([new Uint8Array([1, 2, 3])], "shot.jpg", { type: "image/jpeg" });
    await user.upload(screen.getAllByLabelText("Прикрепить фото")[0], file);
    await user.click(screen.getAllByRole("button", { name: "Отправить" })[0]);

    await waitFor(() => {
      const call = mockFetch.mock.calls.find(
        (entry) => entry[0] === "/support/tickets" && entry[1]?.method === "POST",
      );
      expect(call).toBeTruthy();
      expect(call?.[1]?.body).toBeInstanceOf(FormData);
    });
  });

  it("shows an uploading progress bar while photos are sending", async () => {
    const user = userEvent.setup();
    let finish: ((value: unknown) => void) | undefined;
    mockFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/support/tickets" && init?.method === "POST") {
        return new Promise((resolve) => {
          finish = resolve;
        });
      }
      if (path.startsWith("/support/tickets?")) return listPage([]);
      if (path === "/support/linkable-orders") return [];
      if (path === "/support/tickets/9") return { ...ticketDetailOpen, id: 9 };
      throw new Error(`unexpected ${path}`);
    });
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );
    await screen.findByText("Мои обращения");
    const file = new File([new Uint8Array([1, 2, 3])], "shot.jpg", { type: "image/jpeg" });
    await user.upload(screen.getAllByLabelText("Прикрепить фото")[0], file);
    await user.click(screen.getAllByRole("button", { name: "Отправить" })[0]);
    expect(await screen.findByRole("progressbar", { name: "Загрузка фото" })).toBeTruthy();
    finish?.({ ...ticketDetailOpen, id: 9 });
    await waitFor(() => {
      expect(screen.queryByRole("progressbar", { name: "Загрузка фото" })).toBeNull();
    });
  });

  it("opens attached photos in an in-app preview, not a blob link", async () => {
    const user = userEvent.setup();
    const withPhoto = {
      ...ticketDetailOpen,
      messages: [
        {
          ...ticketDetailOpen.messages[0],
          attachments: [{ id: 99, content_type: "image/jpeg", byte_size: 12 }],
        },
      ],
    };
    mockFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/support/tickets?")) return listPage(ticketList);
      if (path === "/support/linkable-orders") return linkableOrders;
      if (path === "/support/tickets/1") return withPhoto;
      throw new Error(`unexpected ${path}`);
    });
    mockBlobFetch.mockResolvedValue(
      new Blob([new Uint8Array([1, 2])], { type: "image/jpeg" }),
    );
    render(
      <MemoryRouter>
        <SupportSection />
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("button", { name: /#1 / }));
    const thumb = await screen.findByRole("button", { name: "Открыть фото" });
    expect(thumb.closest("a")).toBeNull();
    await user.click(thumb);
    expect(screen.getByRole("dialog", { name: "Фото" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Закрыть фото" }));
    expect(screen.queryByRole("dialog", { name: "Фото" })).toBeNull();
  });

});
