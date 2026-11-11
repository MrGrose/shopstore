import { LoginUnavailableMessage } from "./LoginUnavailableMessage";

export function MiniAppAccessDenied() {
  return (
    <div className="flex h-dvh max-h-dvh flex-col items-center justify-center bg-sp-bg px-6 text-center text-sp-text-secondary">
      <LoginUnavailableMessage className="m-0 max-w-sm text-[15px] leading-relaxed text-sp-text-secondary" />
    </div>
  );
}
