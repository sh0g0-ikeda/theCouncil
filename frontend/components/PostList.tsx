import type { ReactNode } from "react";

import type { PostRecord } from "@/lib/api";

import { PostItem } from "@/components/PostItem";

export function PostList({
  posts,
  renderActions
}: {
  posts: PostRecord[];
  renderActions?: (post: PostRecord) => ReactNode;
}) {
  return (
    <div className="rounded-b-2xl border border-board-border/70 bg-board-paper shadow-board">
      {posts.map((post) => (
        <PostItem
          key={`${post.id}-${post.created_at}`}
          post={post}
          actions={renderActions ? renderActions(post) : undefined}
        />
      ))}
    </div>
  );
}
