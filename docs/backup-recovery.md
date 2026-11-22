# Backup and recovery

Skill metadata and snapshots must be backed up together. Restoring only the database leaves version rows that point to missing files; restoring only files leaves unindexed content.

## PostgreSQL

Create a consistent dump using the deployment's database credentials:

    docker compose exec -T db pg_dump -U agentdock -d agentdock --format=custom > agentdock.dump

Store the dump encrypted in a separate protected location.

## SkillVault

With filesystem storage, back up the named Compose volume skillvault-data with the platform's volume or filesystem snapshot tooling. With S3-compatible storage, enable bucket versioning and back up or replicate the bucket according to the provider's recovery options. Coordinate the storage snapshot with the database dump, or stop web and worker briefly for a consistent recovery point.

## Restore

1. Stop the API and synchronization worker.
2. Restore PostgreSQL and the matching SkillVault volume or object-storage prefix.
3. Run the application release that matches the database schema.
4. Check /api/health, verify sample resource files, then start the worker.
5. Confirm repository statuses, manifests and audit records.

Perform restore drills before production and record expected recovery time and recovery point.
