import { Link } from "react-router";

type Props = {
  className?: string;
};

export function LoginUnavailableMessage({ className }: Props) {
  return (
    <p className={className ?? "m-0"}>
      Вход не доступен. Обратитесь в{" "}
      <Link to="/support" className="text-sp-blue underline">
        поддержку
      </Link>
      .
    </p>
  );
}
