import { Navigate, createFileRoute } from "@tanstack/react-router";

import { buttonVariants } from "@/components/ui/button";
import { OnOffBrand } from "@/components/OnOffBrand";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { loginUrl } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/login")({ component: Login });

function Login() {
  const session = useSession();

  if (session.isLoading) {
    return (
      <main className="flex min-h-svh items-center justify-center p-6">
        <Skeleton className="h-40 w-80" />
      </main>
    );
  }

  if (session.data) {
    return <Navigate to="/my-settings" />;
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md border-border bg-card">
        <CardHeader>
          <OnOffBrand className="mb-5" showMobileCue />
          <CardTitle>Sign in to ON Mobile Agent</CardTitle>
          <CardDescription>Use your corporate Microsoft account.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <a href={loginUrl()} className={cn(buttonVariants({ size: "lg" }), "w-full")}>
            Continue with Microsoft
          </a>
        </CardContent>
      </Card>
    </main>
  );
}
