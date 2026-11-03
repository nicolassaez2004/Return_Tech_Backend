# Avaliação de código com Judge0

A avaliação automática complementa os relatórios, as avaliações humanas e a shortlist existentes. O candidato envia código pelo React; a API Flask valida a inscrição e encaminha os casos privados ao Judge0. Os programas são executados somente no Judge0, com rede desativada e limites de recursos.

## Configuração do backend

Instale as dependências atualizadas com `python -m pip install -r requirements.txt`. Preserve as configurações existentes do MongoDB, JWT e e-mail ao acrescentar estas variáveis ao `.env` da pasta de `run.py`:

```env
JUDGE0_URL=http://127.0.0.1:2358
JUDGE0_API_KEY=
JUDGE0_RAPIDAPI_HOST=
JUDGE0_AUTH_TOKEN=
```

Use em `JUDGE0_AUTH_TOKEN` o token configurado na instância do Judge0. Em um provedor RapidAPI, utilize a URL, a chave e o host fornecidos pelo serviço. Credenciais ficam somente no backend. Use HTTPS para executores remotos; HTTP é aceito apenas em localhost. Reinicie o backend após alterar a configuração. Variáveis definidas no processo têm prioridade sobre o arquivo `.env`.

No frontend, mantenha `VITE_API_URL` apontando para a API Flask, normalmente `http://localhost:5000/api`.

## Iniciar o Judge0 local

Quando a VM Ubuntu `returntech-judge0` já estiver instalada e preparada no Multipass, use:

```powershell
multipass start returntech-judge0
multipass exec returntech-judge0 -- sudo docker compose -f /home/ubuntu/judge0-v1.13.1/docker-compose.yml up -d
```

O redirecionamento de `127.0.0.1:2358` no Windows deve apontar para o IP atual da VM. Esses comandos pressupõem a VM e o Docker Compose previamente configurados; não instalam o Judge0 em um computador novo.

## API e fila de correções

Inicie o backend como indicado no README. Em outro terminal da pasta do backend, mantenha a fila ativa:

```powershell
python -m flask --app run.py process-code-jobs --watch
```

Sem `--watch`, o comando processa uma rodada e encerra. A fila conclui correções mesmo quando o candidato fecha o navegador. Ela é separada do comando `worker`, que processa prazos e e-mails. As opções `MAIL_ENABLED` e `BACKGROUND_JOBS_ENABLED` mantêm o comportamento descrito no README.

## Fluxo de aprovação

1. A empresa cria um desafio e salva como rascunho.
2. Em **Configurar código**, cadastra as linguagens, o exemplo público e os casos privados.
3. Salvar a configuração atualiza a revisão do desafio. A empresa envia o desafio para aprovação.
4. A administração revisa o enunciado e a configuração e aprova a revisão atual. Somente o administrador publica.
5. O talento se inscreve no desafio publicado e envia o código pelo editor.
6. A empresa acompanha as tentativas e a melhor pontuação em **Código e pontos**.

A configuração só pode mudar em um rascunho sem tentativas. A administração pode consultar os casos privados para revisão; a edição pertence à empresa responsável. Desafios pendentes de revisão não ficam disponíveis aos talentos. Após o encerramento, participantes mantêm o histórico, sem novos envios.

## Configuração da avaliação

| Campo | Valores |
| --- | --- |
| `languages` | Lista contendo `python`, `javascript` ou `cpp`. |
| `max_points` | Inteiro de 1 a 10.000. |
| `cpu_time_limit` | CPU por caso, de 0,5 a 5 segundos. |
| `memory_limit_kb` | Memória de 64.000 a 256.000 KB. |
| `example` | Objeto público com `stdin` e `expected_output`. |
| `starter_code` | Código inicial opcional por linguagem. |
| `tests` | De 1 a 20 casos privados com `stdin` e `expected_output`. |

Cada entrada ou saída esperada aceita até 16 KB; o código enviado aceita até 64 KB. O candidato não pode fornecer casos privados, limites nem entrada experimental. O prazo termina no final do dia informado em `CHALLENGE_TIMEZONE`, inicialmente `America/Sao_Paulo`.

A nota é `pontos máximos × casos corretos ÷ total de casos`, arredondada para duas casas decimais. A melhor nota é preservada por candidato e desafio; consultas e reenvios não somam pontos. Falhas do executor não reduzem a melhor nota. Cada candidato pode manter uma tentativa ativa por desafio, com intervalo mínimo de três segundos entre envios. Uma tentativa sem conclusão após cinco minutos é encerrada como falha do serviço e permite novo envio.

## Rotas

Todas as rotas exigem JWT da Return Tech. Os tokens do Judge0 e os casos privados não são retornados aos candidatos.

| Método e rota | Acesso |
| --- | --- |
| `GET /api/challenges/<id>/coding` | Talento inscrito em desafio publicado ou encerrado; empresa responsável; administração. |
| `GET /api/challenges/<id>/coding/config` | Empresa responsável e administração. |
| `PUT /api/challenges/<id>/coding/config` | Empresa responsável, em rascunho sem tentativas. |
| `POST /api/challenges/<id>/code-jobs` | Talento inscrito, desafio publicado e dentro do prazo. |
| `GET /api/code-jobs/<id>` | Dono da tentativa, empresa responsável e administração. |
| `GET /api/challenges/<id>/coding/results` | Empresa responsável e administração. |

O envio contém `language`, `source_code` e, opcionalmente, `mode: "submit"`. A criação responde HTTP 202 com `job._id`. Consulte a tentativa até `completed` ou `service_error`. A API recusa `mode: "run"` e `stdin` enviados pelo candidato. Tentativas experimentais antigas continuam consultáveis para compatibilidade e não recebem pontuação.

## Verificação

Os testes usam MongoDB, SMTP e Judge0 simulados, sem acessar os serviços da equipe:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m unittest discover -s tests -v
```
