FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY backend-core/TechDocIntelligence.Backend.csproj ./
RUN dotnet restore TechDocIntelligence.Backend.csproj

COPY backend-core/. ./
RUN dotnet publish TechDocIntelligence.Backend.csproj -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS final
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV ASPNETCORE_URLS=http://+:5000 \
    ASPNETCORE_ENVIRONMENT=Production

COPY --from=build /app/publish .

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/health || exit 1

ENTRYPOINT ["dotnet", "TechDocIntelligence.Backend.dll"]
