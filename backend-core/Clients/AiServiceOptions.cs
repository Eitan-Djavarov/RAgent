namespace TechDocIntelligence.Backend.Clients;

public sealed class AiServiceOptions
{
    public const string SectionName = "AiService";

    public string BaseUrl { get; set; } = "http://localhost:8000";

    public int TimeoutSeconds { get; set; } = 120;

    public int RetryCount { get; set; } = 2;
}
