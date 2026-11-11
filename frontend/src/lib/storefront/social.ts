import { storefrontApiFetch } from "./api";

export type SocialLinks = {
  telegram_url: string;
  vk_url: string;
  web_catalog_url: string;
  bot_username?: string;
  phone_verification_code_enabled?: boolean;
};

export async function fetchSocialLinks(): Promise<SocialLinks> {
  const data = await storefrontApiFetch<SocialLinks>("/storefront/social");
  if (!data) {
    throw new Error("Не удалось загрузить ссылки");
  }
  return data;
}
