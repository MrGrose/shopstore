import { storefrontApiFetch } from "./api";

export type DeliveryProfile = {
  last_name: string;
  first_name: string;
  street: string;
  house: string;
  apartment: string | null;
  city: string;
  postal_code: string;
  phone: string;
};

// Загружает сохранённый профиль доставки.
export async function fetchDeliveryProfile(): Promise<DeliveryProfile | null> {
  return storefrontApiFetch<DeliveryProfile | null>("/users/me/delivery-profile");
}

// Сохраняет профиль доставки вручную (checkout сохраняет на бэкенде).
export async function saveDeliveryProfile(
  profile: DeliveryProfile,
): Promise<DeliveryProfile> {
  return storefrontApiFetch<DeliveryProfile>("/users/me/delivery-profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}
