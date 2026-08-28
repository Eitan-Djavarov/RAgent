using Microsoft.EntityFrameworkCore;

namespace TechDocIntelligence.Backend.Data;

public sealed class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options)
        : base(options)
    {
    }

    public DbSet<IncidentEntity> Incidents => Set<IncidentEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<IncidentEntity>(entity =>
        {
            entity.HasIndex(e => e.CreatedAt);
            entity.HasIndex(e => e.SystemName);
            entity.HasIndex(e => e.Severity);
            entity.Property(e => e.Title).IsRequired();
            entity.Property(e => e.Description).IsRequired();
            entity.Property(e => e.SystemName).IsRequired();
            entity.Property(e => e.Severity).HasConversion<string>().HasMaxLength(32);
        });
    }
}
