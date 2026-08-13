"""manna: one permanent bank, folded out of the gathered and pending piles

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-13

One column renamed and one sum folded into it. Nothing is created, nothing is
dropped, and no row anywhere else is touched.

THE FOLD. Until this revision manna lived in two places: user_progress.
manna_pending, which was what the calories had come to and had not been
gathered, and the live manna_batches rows, which were what had been gathered and
not yet spent or composted. The release above this one has one balance, so:

    manna = manna_pending + SUM(manna_batches.remaining)
                            over that account's batches with no composted_at

That is the whole of it. His account, 71,940 pending and nothing gathered,
arrives at 71,940; an account that had gathered 500 and spent 150 of it arrives
with the 350 that was still in its hands. Nothing is invented and nothing is
taken: every manna anybody could have spent the moment before this ran is
spendable the moment after.

Read once, here. The manna_batches rows are dormant history from this revision
on: nothing writes them and nothing reads them, and the fruit batches beside
them stay live, because fruit is still gathered and still composts.

WHAT THE FOLD CANNOT CARRY BACK. Manna that composted under the old model is
gone, and it stays gone: it is not in either half of the sum above. A rebuild
after this release works the bank out as the surviving workouts, plus gifts
received, less everything ever spent, which does not know about that loss and
would hand it back. Bounded and one-off, since nothing composts manna any more,
and named here rather than papered over.

THE COLUMN IS RENAMED RATHER THAN ADDED. A second column would leave the old
one holding a number that had already been folded into the new one, which is
exactly the sort of pair that gets added together by mistake one day.

Stepping back is the fold run backwards: the gathered pile is still in
manna_batches, so taking it off the balance and calling what is left pending
lands on the two numbers this started from, as long as nothing has moved in
between. Clamped at zero, because a bank spent down below what the batches say
was gathered would otherwise go negative under a release that has no idea what
a negative pile would mean.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# What is left in the gathered pile, per account: the batches that have not gone
# back to the soil. Spending lowered remaining, so this is what was still in
# somebody's hands.
_LIVE_GATHERED = (
    "SELECT user_id, COALESCE(SUM(remaining), 0) AS held FROM manna_batches"
    " WHERE composted_at IS NULL GROUP BY user_id"
)


def upgrade() -> None:
    op.alter_column("user_progress", "manna_pending", new_column_name="manna")
    connection = op.get_bind()
    for row in connection.execute(sa.text(_LIVE_GATHERED)):
        if not row.held:
            continue
        connection.execute(
            sa.text("UPDATE user_progress SET manna = manna + :held WHERE user_id = :user_id"),
            {"held": int(row.held), "user_id": row.user_id},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for row in connection.execute(sa.text(_LIVE_GATHERED)):
        if not row.held:
            continue
        connection.execute(
            sa.text(
                "UPDATE user_progress SET manna = CASE WHEN manna > :held THEN manna - :held"
                " ELSE 0 END WHERE user_id = :user_id"
            ),
            {"held": int(row.held), "user_id": row.user_id},
        )
    op.alter_column("user_progress", "manna", new_column_name="manna_pending")
