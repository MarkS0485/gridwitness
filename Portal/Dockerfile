# syntax=docker/dockerfile:1.7
# GridWitness account portal (ASP.NET Core 10 MVC). The Tailwind standalone CLI is downloaded by the
# BuildTailwindCss MSBuild target during publish (no Node). Accounts SQLite lives under /app/App_Data.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY Portal.csproj nuget.config ./
RUN --mount=type=secret,id=gh_packages_token GH_PACKAGES_TOKEN="$(cat /run/secrets/gh_packages_token)" dotnet restore Portal.csproj

COPY . .
RUN dotnet publish Portal.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app
COPY --from=build /app ./

ENV ASPNETCORE_URLS=http://+:8080 \
    ASPNETCORE_ENVIRONMENT=Production

EXPOSE 8080
VOLUME ["/app/App_Data"]

ENTRYPOINT ["dotnet", "Portal.dll"]
