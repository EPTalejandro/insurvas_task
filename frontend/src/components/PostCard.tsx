import { useApp } from '../context.ts'
import { compactNumber, humanize, relativeTime } from '../format.ts'
import type { Post } from '../types.ts'
import { AppLink } from './AppLink.tsx'
import { LocationBadge, ScoreBadge } from './Badges.tsx'

function Metric({ name, value }: { name: string; value: number | null }) {
  const shown = value === 1 ? name.slice(0, -1) : name // "1 comment", "2 comments"
  return (
    <span className="metric" title={value === null ? `${name}: not available` : `${name}: ${value}`}>
      <strong>{compactNumber(value)}</strong> {shown}
    </span>
  )
}

export function PostCard({ post }: { post: Post }) {
  const { meta } = useApp()
  const hook = post.title ?? post.label?.hook_text ?? post.text_preview ?? '(no text)'
  const platform = meta.platforms.find((p) => p.id === post.platform)?.label ?? post.platform
  const { label } = post

  return (
    <article className="post-card">
      <a className="thumb" href={post.url} target="_blank" rel="noopener noreferrer">
        {post.thumbnail_url ? (
          <img src={post.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <span className="thumb-empty">{humanize(post.format ?? post.platform)}</span>
        )}
      </a>

      <div className="post-body">
        <div className="post-head">
          <ScoreBadge score={post.score.score} />
          <div>
            <h3 className="post-title">
              <a href={post.url} target="_blank" rel="noopener noreferrer">
                {hook}
              </a>
            </h3>
            <p className="post-meta">
              {post.creator.competitor_id !== null ? (
                <AppLink patch={{ tab: 'competitors', competitor: post.creator.competitor_id }}>
                  {post.creator.name}
                </AppLink>
              ) : (
                <span>{post.creator.name}</span>
              )}
              {' · '}
              {platform}
              {post.format && ` · ${humanize(post.format)}`}
              {` · ${relativeTime(post.published_at)}`}
            </p>
          </div>
        </div>

        <div className="chips">
          {label?.topic && (
            <AppLink
              className="chip"
              patch={{ tab: 'content', topic: label.topic }}
              title="Show only this topic"
            >
              {humanize(label.topic)}
            </AppLink>
          )}
          {label?.hook_type && (
            <AppLink
              className="chip"
              patch={{ tab: 'content', hook_type: label.hook_type }}
              title="Show only this kind of hook"
            >
              Hook: {humanize(label.hook_type)}
            </AppLink>
          )}
          {label?.cta && label.cta !== 'none' && (
            <span className="chip chip-static" title="Call to action">
              CTA: {humanize(label.cta)}
            </span>
          )}
          <LocationBadge location={post.location} />
        </div>

        <div className="metrics">
          <Metric name="views" value={post.metrics.views} />
          <Metric name="likes" value={post.metrics.likes} />
          <Metric name="comments" value={post.metrics.comments} />
          <Metric name="shares" value={post.metrics.shares} />
        </div>

        {post.score.reason && <p className="reason">{post.score.reason}</p>}
      </div>
    </article>
  )
}
