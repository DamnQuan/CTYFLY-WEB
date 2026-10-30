<script setup>
import { inject } from 'vue';
import { fmtTime } from '../../utils.js';
import Icon from '../Icon.vue';
import UserAvatar from '../UserAvatar.vue';
const {
  addComment,
  authUserId,
  deletePost,
  isCeo,
  newComments,
  newPost,
  pinPost,
  posts,
  postsLoading,
  publishPost,
  toggleLike,
} = inject('airlinePage');
</script>

<template>
<div class="glass card">
        <div class="card-title">航司动态</div>
        <div class="card-sub">内部公告与交流，成员可点赞评论{{ isCeo ? '，CEO 可置顶与删除' : '' }}</div>

        <div style="margin-bottom: 18px">
          <textarea v-model="newPost" class="textarea" rows="2" maxlength="1000" placeholder="发布一条动态或公告…"></textarea>
          <button class="btn btn-primary btn-sm" style="margin-top: 10px" @click="publishPost">发布</button>
        </div>

        <div v-if="postsLoading" class="loading">加载中…</div>
        <template v-else>
          <div v-for="p in posts" :key="p.id" class="post-item">
            <div style="display: flex; gap: 12px">
              <UserAvatar :user="{ avatar_url: p.author_avatar, username: p.author_name }" :size="36" />
              <div style="flex: 1; min-width: 0">
                <div class="list-title">
                  <span v-if="p.pinned" class="tag tag-red" style="margin-right: 6px">置顶</span>
                  {{ p.author_name }}
                  <span class="tag" style="margin-left: 6px">{{ p.author_rank || '学员' }}</span>
                </div>
                <div class="list-sub">{{ fmtTime(p.created_at) }}</div>
                <div style="margin: 8px 0; font-size: 14px; white-space: pre-wrap; word-break: break-word">{{ p.content }}</div>

                <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
                  <button class="btn btn-ghost btn-sm" :class="{ 'liked': p.liked }" @click="toggleLike(p)">
                    <Icon name="heart" :size="13" /> {{ p.liked ? '已赞' : '点赞' }} {{ p.like_count || '' }}
                  </button>
                  <span v-if="p.comments?.length" class="list-sub" style="display: inline-flex; align-items: center; gap: 5px">
                    <Icon name="message" :size="13" /> {{ p.comments.length }}
                  </span>
                  <template v-if="isCeo">
                    <button class="btn btn-ghost btn-sm" @click="pinPost(p)">
                      <Icon name="pin" :size="13" /> {{ p.pinned ? '取消置顶' : '置顶' }}
                    </button>
                  </template>
                  <button
                    v-if="isCeo || p.author_id === authUserId"
                    class="btn btn-danger btn-sm"
                    @click="deletePost(p)"
                  ><Icon name="trash" :size="13" /> 删除</button>
                </div>

                <div v-if="p.comments?.length" class="post-comments">
                  <div v-for="c in p.comments" :key="c.id" class="list-sub" style="margin-top: 6px">
                    <strong>{{ c.username }}</strong>：{{ c.content }}
                  </div>
                </div>

                <div class="input-row" style="margin-top: 10px">
                  <input
                    v-model="newComments[p.id]"
                    class="input"
                    placeholder="写条评论…"
                    @keyup.enter="addComment(p)"
                  />
                  <button class="btn btn-ghost btn-sm" @click="addComment(p)">发送</button>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!posts.length" class="empty">还没有动态，来发第一条吧</div>
        </template>
      </div>
</template>

<style scoped>
.post-item { padding: 16px 12px; margin: 0 -8px; border-radius: 12px; border-bottom: 1px solid var(--border); transition: background 0.16s ease; }
.post-item:hover { background: var(--surface); }
.post-item:last-child { border-bottom: none; }
.post-comments { margin-top: 10px; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--surface); }
.btn-ghost.liked { color: #ff3b30; }
.btn-ghost.liked :deep(svg) { fill: currentColor; }
</style>
