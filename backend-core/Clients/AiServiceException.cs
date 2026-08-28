using System.Net;

namespace TechDocIntelligence.Backend.Clients;

public sealed class AiServiceException : Exception
{
    public AiServiceException(
        string message,
        HttpStatusCode? statusCode = null,
        string? responseBody = null,
        IReadOnlyDictionary<string, string>? responseHeaders = null)
        : base(message)
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
        ResponseHeaders = responseHeaders;
    }

    public AiServiceException(
        string message,
        Exception innerException,
        HttpStatusCode? statusCode = null,
        string? responseBody = null,
        IReadOnlyDictionary<string, string>? responseHeaders = null)
        : base(message, innerException)
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
        ResponseHeaders = responseHeaders;
    }

    public HttpStatusCode? StatusCode { get; }

    public string? ResponseBody { get; }

    public IReadOnlyDictionary<string, string>? ResponseHeaders { get; }
}
