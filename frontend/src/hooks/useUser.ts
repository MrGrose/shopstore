import { useQuery, type QueryClient } from "@tanstack/react-query";

import { fetchCurrentUser, type StorefrontUser } from "../lib/storefront/session";

export const userQueryKey = ["user", "me"] as const;

export function syncUserQueryCache(
  queryClient: QueryClient,
  user: StorefrontUser | null,
): void {
  queryClient.setQueryData(userQueryKey, user);
}

export async function invalidateUserQuery(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: userQueryKey });
  await queryClient.fetchQuery({
    queryKey: userQueryKey,
    queryFn: fetchCurrentUser,
  });
}

export function useUser(): {
  user: StorefrontUser | null | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => Promise<unknown>;
} {
  const query = useQuery<StorefrontUser | null, Error>({
    queryKey: userQueryKey,
    queryFn: fetchCurrentUser,
  });

  return {
    user: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
