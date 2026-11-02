import { useState } from 'react'
import { useApp } from '../context.ts'
import { compactNumber, humanize, plainReason, relativeTime } from '../format.ts'
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

/**
 * The preview image. YouTube links last; Instagram links expire after about 4 days, so a broken
 * image falls back to a text placeholder instead of an empty box. `no-referrer` keeps the
 * Instagram CDN from seeing which page shows the image.
 */
function Thumb({ post }: { post: Post }) {
  const [broken, setBroken] = useState(false)
  // Taller than wide (Reels, portrait images): known only once the image loads, since the API
  // gives no size. The CSS then makes the box taller so the picture is not tiny.
  const [tall, setTall] = useState(false)
  if (post.thumbnail_url && !broken) {
    return (
      <img
        src={post.thumbnail_url}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        className={tall ? 'tall' : undefined}
        onLoad={(event) => setTall(event.currentTarget.naturalHeight > event.currentTarget.naturalWidth)}
        onError={() => setBroken(true)}
      />
    )
  }
  return (
    <span
      className="thumb-empty"
      title={post.thumbnail_url ? 'The image link expired. Collect again to renew it.' : undefined}
    >
      {humanize(post.format ?? post.platform)}
    </span>
  )
}

/**
 * Top content's seen state for one card. `onOpen` runs when the post's link is opened; `note`
 * and `action` describe the line under the card (none when `note` is null); `dimmed` marks a
 * card that has already moved to the other view but stays in place until the list reloads.
 */
export interface SeenControl {
  onOpen: () => void
  note: string | null
  action: string
  onAction: () => void
  dimmed: boolean
}

/** `lead` is the best post of a list: it gets the biggest numeral. */
export function PostCard({ post, lead = false, seen }: { post: Post; lead?: boolean; seen?: SeenControl }) {
  const { meta } = useApp()
  const hook = post.title ?? post.label?.hook_text ?? post.text_preview ?? '(no text)'
  const platform = meta.platforms.find((p) => p.id === post.platform)?.label ?? post.platform
  const { label } = post
  // A left click and a middle click both open the link in a new tab, so both count as seen.
  const opened = seen ? { onClick: seen.onOpen, onAuxClick: seen.onOpen } : {}
  const classes = ['post', lead && 'post-lead', seen?.dimmed && 'is-seen'].filter(Boolean).join(' ')

  return (
    <article className={classes}>
      <ScoreBadge score={post.score.score} />

      <div className="post-body">
        <h3 className="post-title">
          <a href={post.url} target="_blank" rel="noopener noreferrer" {...opened}>
            {hook}
          </a>
        </h3>

        <p className="meta-line">
          {post.creator.competitor_id !== null ? (
            <AppLink patch={{ tab: 'competitors', competitor: post.creator.competitor_id }}>
              {post.creator.name}
            </AppLink>
          ) : (
            <span>{post.creator.name}</span>
          )}
          <span>{post.format ? `${platform} ${humanize(post.format).toLowerCase()}` : platform}</span>
          <span>{relativeTime(post.published_at)}</span>
          <LocationBadge location={post.location} />
        </p>

        <p className="post-stats">
          <Metric name="views" value={post.metrics.views} />
          <Metric name="likes" value={post.metrics.likes} />
          <Metric name="comments" value={post.metrics.comments} />
          <Metric name="shares" value={post.metrics.shares} />
          {post.score.reason && <span className="reason">{plainReason(post.score.reason)}</span>}
        </p>

        <p className="tags">
          {label?.topic && (
            <AppLink className="tag" patch={{ tab: 'content', topic: label.topic }} title="Show only this topic">
              {humanize(label.topic)}
            </AppLink>
          )}
          {label?.hook_type && (
            <AppLink
              className="tag"
              patch={{ tab: 'content', hook_type: label.hook_type }}
              title="Show only this kind of hook"
            >
              Hook: {humanize(label.hook_type)}
            </AppLink>
          )}
          {label?.cta && label.cta !== 'none' && (
            <span className="tag tag-static" title="Call to action">
              CTA: {humanize(label.cta)}
            </span>
          )}
        </p>

        {seen?.note && (
          <p className="seen-line">
            <span>{seen.note}</span>
            <button className="link-button" onClick={seen.onAction}>
              {seen.action}
            </button>
          </p>
        )}
      </div>

      <a
        className="thumb"
        href={post.url}
        target="_blank"
        rel="noopener noreferrer"
        tabIndex={-1}
        aria-hidden="true"
        {...opened}
      >
        <Thumb key={post.thumbnail_url ?? post.id} post={post} />
      </a>
    </article>
  )
}
