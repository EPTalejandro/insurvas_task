from sqlalchemy import select

from app.models import Creator, Label, Post


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_models_round_trip(session):
    creator = Creator(platform="youtube", external_id="UC123", handle="@agent", name="Agent")
    post = Post(
        creator=creator,
        platform="youtube",
        external_id="vid1",
        url="https://youtube.com/watch?v=vid1",
        source="youtube_api",
    )
    post.label = Label(topic="term_life", labeler="rules")
    session.add(post)
    session.commit()

    saved = session.scalars(select(Post)).one()
    assert saved.creator.handle == "@agent"
    assert saved.label.topic == "term_life"
