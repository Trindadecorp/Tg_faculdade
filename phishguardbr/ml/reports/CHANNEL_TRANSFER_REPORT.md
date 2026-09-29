# Transferência entre canais — e-mail × SMS

> Gerado por `src/training/channel_transfer.py`. Métricas na classe spam.
> Treino: e-mail 83,044 | SMS 4,116. Teste: e-mail 20,762 | SMS 1,029.

Os conjuntos de teste são fixos em todas as linhas; varia apenas o treino.
O vocabulário TF-IDF é ajustado somente sobre o treino de cada célula.

## Matriz (melhor F1 por célula)

| treino   |   e-mail |    SMS |
|:---------|---------:|-------:|
| e-mail   |   0.9723 | 0.3534 |
| SMS      |   0.3787 | 0.9551 |
| ambos    |   0.9696 | 0.6592 |

## Leitura

**SMS é aprendível.** Treinado no próprio canal, o modelo atinge F1 **0.9551** sobre SMS. A falha do modelo de e-mail nesse canal não se explica por dificuldade intrínseca da tarefa.

**O conhecimento de e-mail não transfere.** O mesmo teste de SMS, servido por um modelo treinado em e-mail, cai para F1 **0.3534** — contra **0.9723** que esse modelo entrega no seu próprio canal. A queda é de transferência, não de tarefa.

**Treinar nos dois canais junto.** O modelo misto entrega F1 **0.6592** em SMS e **0.9696** em e-mail.

O modelo misto não recupera o desempenho dos modelos dedicados em pelo menos um dos canais.

**Diagnóstico da linha `ambos`.** O SMS representa apenas 4.7% do treino misto (4,116 de 87,160). A queda em SMS pode, portanto, ser efeito do mesmo desbalanceamento que a §5.5 trata por teto de amostragem — e não uma incompatibilidade de fundo entre os canais. Distinguir as duas hipóteses exige repetir esta linha com o corpus de SMS ampliado ou com reponderação por canal; enquanto isso não for feito, a conclusão segura é a da diagonal: **cada canal precisa do seu próprio corpus**.

## Consequência para o produto

O escopo multicanal exige **corpus por canal**, não apenas modelo por canal. Como não existe corpus público de phishing/smishing em PT-BR para nenhum dos dois, a construção do corpus brasileiro é pré-requisito do escopo multicanal, e não um complemento dele.

## Limitação

O corpus de SMS disponível é pequeno (5,145 mensagens, fonte única — SMS Spam Collection/UCI) e em inglês. Os resultados da linha SMS devem ser lidos como indicativos; sua confirmação depende do corpus PT-BR de SMS previsto na Fase 5.

## Detalhamento

| treino   | teste   | modelo         |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:---------|:--------|:---------------|-----------:|------------:|---------:|-------:|----------:|
| e-mail   | e-mail  | logreg         |     0.9738 |      0.9653 |   0.9632 | 0.9642 |    0.9959 |
| e-mail   | e-mail  | linear_svc     |     0.9796 |      0.9695 |   0.9751 | 0.9723 |    0.9971 |
| e-mail   | e-mail  | multinomial_nb |     0.9564 |      0.9497 |   0.9305 | 0.94   |    0.9903 |
| e-mail   | SMS     | logreg         |     0.4276 |      0.162  |   0.881  | 0.2737 |    0.6789 |
| e-mail   | SMS     | linear_svc     |     0.4276 |      0.1601 |   0.8651 | 0.2701 |    0.6832 |
| e-mail   | SMS     | multinomial_nb |     0.6657 |      0.2315 |   0.746  | 0.3534 |    0.7697 |
| SMS      | e-mail  | logreg         |     0.6344 |      0.5139 |   0.0922 | 0.1563 |    0.5761 |
| SMS      | e-mail  | linear_svc     |     0.6158 |      0.4665 |   0.3187 | 0.3787 |    0.5894 |
| SMS      | e-mail  | multinomial_nb |     0.6288 |      0.4189 |   0.0267 | 0.0503 |    0.5979 |
| SMS      | SMS     | logreg         |     0.9699 |      0.9897 |   0.7619 | 0.861  |    0.9972 |
| SMS      | SMS     | linear_svc     |     0.9893 |      0.9832 |   0.9286 | 0.9551 |    0.9976 |
| SMS      | SMS     | multinomial_nb |     0.9708 |      1      |   0.7619 | 0.8649 |    0.9855 |
| ambos    | e-mail  | logreg         |     0.9679 |      0.9708 |   0.9409 | 0.9556 |    0.9955 |
| ambos    | e-mail  | linear_svc     |     0.9777 |      0.9732 |   0.966  | 0.9696 |    0.9966 |
| ambos    | e-mail  | multinomial_nb |     0.9545 |      0.9522 |   0.9224 | 0.9371 |    0.9902 |
| ambos    | SMS     | logreg         |     0.8834 |      0.5135 |   0.9048 | 0.6552 |    0.9514 |
| ambos    | SMS     | linear_svc     |     0.8824 |      0.5109 |   0.9286 | 0.6592 |    0.9665 |
| ambos    | SMS     | multinomial_nb |     0.8406 |      0.4246 |   0.8492 | 0.5661 |    0.9126 |

