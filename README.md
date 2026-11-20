# GMT — protótipo local

Protótipo de consulta de jornadas baseado exclusivamente em evidências da pasta `kb/`.
O pipeline é determinístico e não chama modelos, APIs ou serviços externos. Ele não
substitui autenticação, revisão humana nem aprovação institucional.

## Restrições atuais

- `provider.kind` deve permanecer `disabled`; não há provedor/modelo institucional aprovado configurado.
- A configuração atual usa `authorization.mode: local` e identidade sintética, sem login. Esse modo só inicia com `environment: local` e bind `127.0.0.1`; use exclusivamente dados fictícios e não o exponha em rede.
- Para OIDC institucional, altere `authorization.mode` para `oidc`; a allowlist começa vazia e deve ser fornecida via `GMT_ALLOWED_USER_IDS` após autorização. Não versione IDs pessoais.
- A base `kb/` está vazia. Sem documentos aprovados e vigentes, as perguntas retornam `insufficient_context`.
- O histórico é mantido somente em memória do processo, isolado por sessão e identidade, com expiração.
- O log de auditoria omite pergunta e resposta e remove registros além de `audit.retention_days`, configurado para 90 dias. Confirme que esse prazo atende à política institucional; ACL e destino institucional também precisam de validação.
- O protótipo não é adequado para produção. A aprovação humana do escopo, do provedor, da retenção e da implantação continua pendente.

## Documentos da base de conhecimento

Markdown deve conter front matter YAML; YAML deve declarar `content`. Ambos precisam
dos campos `id`, `version`, `updated_at` e `valid_until` (`YYYY-MM-DD`), além de
`status: approved`, `approved_by` e `approval_reference`. PDF, DOCX, XLSX e TXT
precisam de um arquivo de metadados ao lado, por exemplo `jornada.pdf.meta.yaml`,
com os mesmos campos. A aplicação valida a presença desses marcadores, mas não
consulta o sistema institucional de aprovações; a aprovação deve ser verificada
por um responsável antes da inclusão. Documentos não aprovados, sem metadados ou
vencidos nunca fundamentam respostas. Arquivos e instruções incorporadas são
tratados como dados não confiáveis.

Exemplo fictício de `kb/jornada.md`:

```yaml
---
id: jornada-exemplo
version: "1.0"
updated_at: "2026-01-01"
valid_until: "2027-01-01"
status: approved
approval_reference: "APROVACAO-FICTICIA-001"
approved_by: "Aprovador fictício"
---
O fluxo fictício começa pela identificação da jornada.
```

## Execução

Use Python 3.11 ou superior em ambiente aprovado. Instale as dependências após
avaliação institucional e execute. O extra `streamlit[auth]` instala o Authlib
necessário para o fluxo OIDC de `st.login()`:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

Por padrão, o Streamlit escuta somente em `127.0.0.1` e a coleta de estatísticas
de uso fica desativada. Não altere o endereço de escuta sem aprovação de rede e
autenticação do ambiente.

No modo OIDC, configure o provedor do Streamlit no ambiente autorizado. O arquivo
`.streamlit/secrets.toml` precisa conter as chaves `redirect_uri`,
`cookie_secret`, `client_id`, `client_secret` e `server_metadata_url` dentro da
seção `[auth]`; obtenha os valores do administrador do provedor institucional.
Use `http://localhost:8501/oauth2callback` como `redirect_uri` somente no
desenvolvimento local e registre essa URL no provedor. Nunca envie credenciais
por chat ou versione `secrets.toml` (ele está no `.gitignore`). O app verifica
se essas configurações existem antes de chamar `st.login()`, e exige também
identidade autenticada presente na allowlist aprovada. O modo local ignora
`secrets.toml`, não faz login e só aceita a identidade sintética local.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Os testes usam apenas documentos fictícios temporários. O log local fica em
`logs/audit.jsonl`; proteja-o e aplique retenção institucional antes de usar dados
reais.
